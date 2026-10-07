# Specification: Context Layer schemas, terminology and identifier knowledge

| | |
| :--- | :--- |
| **Status** | **Approved, revision 1 — written review complete** |
| **Approval** | Owner, Pi conversation 2026-10-02: requested “shape the design”; selected closer generation rather than generic OKF import, automatic draft persistence, and equality/prefix/lookup discovery. After the complete eight-section design was presented, selected “Approve and capture”, explicitly including relevant-pages-only bundles and context-only admission before the first metric. Subsequently approved this written revision with “approved.” in the same conversation. Approval authorizes this specification, vocabulary, qualifying ADR and scoped contract cross-references; not implementation, ticket changes, integration or publication. |
| **Scope** | Richer generated Ariadne OKF artifacts; source-qualified physical schemas; shared terminology and identifier References; bounded measured mapping inspection; automatic hypothesis capture in Git Authoring Proposals; human-only admission. |
| **Sources** | [Research comparison](../research/2026-10-02-context-layer-okf-and-identifiers.md), [modular-core/Git authoring](2026-10-02-0009-modular-core-git-authoring.md), [harness-led authoring](2026-09-24-0005-harness-led-authoring.md), [Context retrieval](2026-09-23-0002-context-retrieval.md), [Agent roles](2026-09-29-0006-ariadne-agent-backend.md), [vocabulary](../../CONTEXT.md), [ADR-0017](../adr/0017-context-schema-and-identifier-knowledge.md). |
| **Contract** | planning-contract v1; installed skill provenance unknown. |

**Later scoped consumer extension (owner, 2026-10-06):** [specification 0011](2026-10-06-0011-context-trust-signals.md), approved design revision 1, corrects freshness readers and adds advisory `context_signals` to existing search, term and metric results. It preserves this specification's generation requirements, source/admission/confirmation authority, mapping-evidence checks, bounded disclosure, full rule text and search eligibility. Producer changes, recursive dependency traversal, lifecycle-based refusals and the OKF executor/receipt ABI remain outside that round.

## 1. Purpose, boundaries and alternatives

Make a data project's Context Layer closer to Google's OKF v0.2 examples without creating a second authoritative knowledge store. Share physical schemas and source-linked business meaning, distinguish language aliases from identifier equivalence, and let an Authoring Agent investigate and retain hypotheses rather than rediscovering them each session.

Extend Ariadne's existing OKF application profile, not its execution format. Keep one `ariadne-core` distribution, the `ariadne` namespace, DuckDB, SQLGlot, OSI, optional MCP and the separately installed Agent. Use the shared modules and exact-revision Git lifecycle approved in specification 0009. The Context Layer guides; the Semantic Layer calculates; source approval and human artifact admission remain separate.

Alternatives considered: a separate synonym/rule registry would duplicate meaning and introduce synchronization/authority problems; generic OKF import/export and Google's richer computation executor/receipt contract add scope not needed for this use case. The owner selected closer generation and one OKF store.

Non-goals: generic OKF bundle import/export; a generic ontology or executable rule interpreter; embeddings, vector databases or an unmeasured search-ranking overhaul; new connectors/backends/dependencies; arbitrary model-supplied SQL, shell, Git or filesystem operations; autonomous source approval, business-meaning approval or admission; normalization beyond the approved equality/prefix/explicit-lookup families; copying datasets into the wiki; changing governed metric arithmetic, required Policies, fact-local aggregation or independent-attestation meaning; remote publication, HTTP deployment, ticket changes or implementation.

## 2. Ownership and lifecycle

| Owner | Responsibility |
| :--- | :--- |
| **Execution** | Inspect approved catalog assets and perform guarded, read-only profiling/mapping measurements. Source locations/credentials remain operator-owned. |
| **Shared Context** | Represent and validate supported OKF pages/extensions, generate physical factual content and indexes, resolve terminology and citations, and distinguish hypotheses from confirmed assertions. |
| **Authoring** | Read admitted/candidate knowledge, generate bounded investigation candidates, capture hypotheses/evidence, ask about unresolved meaning and propose page/model edits. |
| **Shared Semantic** | Own executable OSI definitions, grains, relationship checks, normalized fields and conformed dimensions; no calculation is sourced from wiki prose. |
| **Shared Proposals / human admission** | Reuse isolated Git proposals, revision-checked edits, full matching validation/review evidence and pinned admitted snapshots. Only a human admits business assertions at the exact reviewed revision. |

CLI, Python, MCP and native Agent adapters call the same core behavior. Do not build a parallel parser, compiler, proposal mechanism or interpretation store per adapter. Authoring can inspect its selected candidate before any metric exists. Analyst resolves admitted context; Authoring can read/resolve its explicitly selected proposal, with unadmitted identity visible. The existing fixed-role boundary remains intact.

Automatic hypothesis persistence is authorized within the existing operator-approved authoring/source access. It is a proposal edit, not approval or serving. The agent cannot change source/sample permissions, clear exhausted repair state or bypass stale-revision/one-writer safeguards. Generated schema/evidence/index content is finalized before the candidate commit is validated and reviewed; separate admission evidence must not decorate admitted bytes afterward.

## 3. Bundle layout and applicable-page validation

```text
context_layer/
  datasets/              # Physical source/collection overviews
  tables/                # Physical schema and column meaning
  references/            # Shared terminology, identifier mappings, enums
    joins/               # Existing join References
  policies/
  metrics/
  computations/
  skills/
```

Use `type: dataset` for Dataset Overviews, existing `type: table` for physical tables, and `type: reference` for general and join References. Term References and Identifier Mappings are roles within References, not new standalone page types. A versioned `ariadne` extension distinguishes and structures the new knowledge. Dataset Overview is not an OSI dataset. Preserve existing lower-case types and governed extensions.

Require applicable pages and dependencies, not artificial presence of every category. The authored scope identifies the approved assets it documents; each documented table has its schema page, and each represented physical collection has its Dataset Overview and table links. An unrelated approved source is not silently asserted to have been documented. Unmodeled tables do not require invented metrics, Policies, computations, joins or operational guides.

Every included page must satisfy its per-type contract. Every modeled metric still needs its matching OSI definition, cited applicable Policy pages and generated computation. Every declared relationship/field dependency must resolve and meet its existing safety checks. Applicable directories receive generated indexes; the root retains its index/log, and newly generated root index may declare `okf_version: "0.2"`. These remain system-owned.

A physical table may have unknown Grain. A profiler's unique columns are explicitly candidate keys, not automatically business-key declarations or `STRICT_1_TO_1` guarantees. Any declared physical-table Grain must identify its source of authority/evidence. Semantic datasets still require declared Grain and live checks; this amendment does not allow keyless governed calculations.

Support the new general References and approved structured fields consistently across authoring and standalone ingestion. Ingestion preserves allowed aliases/bindings and its actual document provenance, without allowing document text to invent measured receipts or approval. A document's claimed schema/relationship is cited authored meaning until measured against approved assets; ingestion itself neither registers nor opens a newly mentioned data location. Its staging, human Promotion and opt-in Policy reconciliation boundaries remain unchanged.

## 4. Physical schema representation and refresh

### Identity

Each Dataset Overview/table has an explicit, stable, credential-free `resource` identifying the approved source and catalog path. The identity includes schema/collection distinctions where present and is stable across worktrees/snapshots. Bindings use the actual catalog identity, not an ambiguous unqualified `orders` or a guessed schema. Source-qualified filenames are navigational; `resource` is authoritative. A filename/resource collision must not overwrite another asset.

Exact URI serialization and page-slug encoding belong to the implementation plan. They must be deterministic and unambiguous for supported source/catalog identifiers, preserve existing source identities and avoid credentials or machine-specific operational paths. Source renaming is not introduced as a separate mutation capability.

### Content and ownership

The core generates physical facts from catalog inspection and measured profiles. The agent authors sourced meaning. A table page presents:

- Summary and established row meaning, or an explicit unknown.
- `# Schema`: physical column inventory/types and declared metadata supported by the source.
- Separately labeled observations: row/null/distinct statistics, scope/time and candidate keys.
- Column meanings, units, relevant Policies, pitfalls and established examples.
- Ordinary Markdown links to related tables, Term References, joins, Policies and modeled computations where relevant.

Expose declared nullability/defaults/comments/constraints only where the source provides them; unavailable metadata remains unknown. Zero observed nulls is not a declared `NOT NULL`, and observed uniqueness is not a permanent business guarantee. Measurements can be sampled or incomplete; omitted facts are not empty values or successful checks.

Explicit authoring refresh updates generated facts in the selected proposal, never admitted pages during a query. Preserve authored meanings for unchanged column identities. Flag removed columns and changed names/types; do not guess a rename or attach an old meaning to a different field. Retain prior explanation/evidence in the proposal/history for review. Refresh with unchanged inputs/content is a no-op under the existing proposal contract; timestamps are not regenerated merely to create a different candidate.

Domain claims use stable `sources[].id` footnotes. Cite the actual input document/owner evidence for business meaning and the identified catalog/profile for physical facts. Preserve digest linkage. Objective source-author/modification signals may be included when known; do not fabricate usage counts, credibility scores or source dates. New timestamp-valued metadata uses explicit-offset ISO 8601 datetimes. Evidence freshness follows recorded dependencies and stated scope; expired evidence is visibly stale. Per-family freshness policy must be made concrete in planning without treating a TTL as proof that live data is unchanged.

Computation pages remain generated from OSI, with honest `attestation: pending` when no independent expected-value oracle exists. This revision does not implement the Google executor/receipt ABI or relabel compile checks as independent attestation.

## 5. Term References and Identifier Mappings

A Term Reference represents one shared business concept and contains page-level aliases, representation-specific aliases, actual field bindings, required scope, disambiguations, Identifier Mappings, measured evidence and links to governing Policies/OSI implementations.

The versioned `ariadne` extension must have the smallest structure needed by the consumers: a reference-role discriminator; stable representation IDs and their aliases, source-qualified field bindings and scope; stable mapping IDs, approved mapping family, representation endpoints, claim classification and evidence dependencies; and applicable Policy/OSI links. The plan defines the exact schema/version and rejects malformed supported-extension content without accepting author-fabricated system-owned fields. No second synonym file/database or independently editable copy of executable OSI SQL is introduced.

Distinguish:

| Kind | Meaning |
| :--- | :--- |
| **Language alias** | An alternate name for a concept/representation. It is not value equivalence or permission to join. |
| **Representation** | A concept as carried by identified fields, with its required store/tenant/time scope. |
| **Mapping hypothesis** | A proposed relationship whose meaning or applicability is unresolved. |
| **Asserted mapping** | A declaration supported by cited domain evidence/owner clarification and presented for human review. It is not confirmed merely because an agent writes it. |

Human admission of a Reference as investigative knowledge does not confirm mappings classified as hypotheses. Confirmed use requires an asserted mapping with matching evidence/dependencies and explicit human admission evidence bound to the reviewed assertion/revision. Human review/confirmation is operational evidence, not an agent-authored flag or post-review artifact mutation. The admission/review interface must expose which mapping assertions, if any, are being confirmed. A hypothesis remains labeled and non-authoritative even in an admitted page.

The owner's order-number example is illustrative, not a rule automatically installed in every project:

```text
local identity: (store_id, local_order_number)
(ABC, 123123) -> ABC123123
(XYZ, 123123) -> XYZ123123
```

Record different local/global representations. Prefix uniqueness, formatting, historical changes and possible local-number reset scope must be established for the real project. Preserve `00123` unless an explicitly supported, confirmed representation rule establishes otherwise; do not infer normalization from an integer cast. Missing prefixes, unknown stores, ambiguous concatenation or exceptions remain visible. Do not strip assumed prefix lengths, suffix-match identities, silently trim/pad/case-fold, or join on the local number alone.

A Reference explains the relation; a Policy owns confirmed normative business rules; OSI owns its executable expression. Existing conformed dimensions may align normalized, reviewed group keys, never prove raw-value equivalence or authorize raw fact-to-fact joins.

## 6. Terminology resolution

Add a shared, read-only `resolve_term` operation exposed through local Python/CLI and appropriate MCP/native Agent roles. Query resolves its pinned admitted context; Authoring may resolve an explicitly selected candidate revision. The host owns project/root selection. This is not an arbitrary file reader or a mutation capability.

Return bounded matching concept/representation identities, field bindings, required scope, ambiguity, claim/confirmation status, evidence freshness and page/source citations. Preserve the admitted-versus-proposal identity and revision. Alias matching is deterministic, case-insensitive for natural language and respects whole aliases/phrases; physical field binding uses exact catalog identity, not natural-language normalization. Exact qualified-field lookup can retrieve its documented meaning. Multiple valid matches remain alternatives; ranking must not invent unique identity.

Examples: “global order number” can resolve the documented global representation; umbrella “order number” returns local/global choices; unconfirmed or stale mappings remain visible leads with their limitations, not approved substitutions. No matching term returns no matches; malformed/unauthorized references fail explicitly.

`search_context` retains its existing full-page content, passage pointers, eligible pages and draft labeling. Do not replace returned metric/Policy bodies or tune its ranking without the existing measured-retrieval gates. Term resolution does not rewrite SQL, automatically apply transforms, authorize joins or make an Ad-hoc Metric governed.

Context discovery/resolution must work on a human-admitted context-only Git revision before any metric exists. Metric operations retain a specific missing-catalog error; no absent model triggers fallback raw SQL. Legacy explicit artifact-root discovery is not silently reclassified as Git admission.

## 7. Bounded mapping inspection

Add one typed Authoring `inspect_mapping` operation, reusable by Python/CLI, Authoring/Combined MCP and the native Authoring role. It measures candidates; it does not grant the Analyst arbitrary data-query authority or automatically edit/admit artifacts.

Supported candidate families:

1. **Equality:** exact equivalence/containment between compatible identified fields or composite tuples, with scope and null treatment explicit; no silent lossy type conversion.
2. **Prefix:** construction from identified prefix/local components, including a scoped explicit prefix lookup. Formatting assumptions are part of the candidate; unsupported normalization remains unresolved.
3. **Lookup:** an explicit approved lookup's scoped key/value mapping, with duplicate/unknown-key and multiplicity evidence. A many-valued lookup is not silently collapsed into a unique mapping.

Requests identify the selected proposal/revision, participating approved catalog assets/columns, structured candidate and bounded scope. Core validates identities and approved source/sample permissions before reads. The agent supplies no SQL, shell command, filesystem root, arbitrary function or freely interpreted expression. Cross-source candidates are allowed only when every participating source is approved. Reuse Execution and the existing read-only/statement safety mechanisms for core-generated inspection statements; no independent compiler or raw-query tool is exposed.

Operator-owned finite sample-row, execution-time and response limits apply. The agent cannot raise ceilings or grant value-sample permission. Row limits bound inspected materialized samples/output, not a promise of cheap physical scans; execution/time budgets must prevent unbounded work, and the actual tested scope must be disclosed. Default output is aggregate evidence and shape summaries; returning raw identifier examples requires explicit operator sample permission. No whole order/customer dataset is copied into the proposal.

Measured inputs add bounded identifier-shape summaries for requested investigation candidates, not an exhaustive all-column/all-pair scan. These help suggest equality/prefix/lookup candidates without asserting them as business rules.

A core-produced Mapping Evidence receipt identifies:

- Exact structured candidate/declaration and digest; participating asset/column and approved resolved source identities.
- Measurement time, supplied source-version evidence when available, selected scope/strata and sampled/full designation.
- Tested/eligible counts and null/missing-component/unknown-lookup counts.
- Match coverage/denominators, mismatches, collisions and join multiplicity.
- Whether support is value containment only or comparison using independently paired records/keys.
- Completion/limitation outcome, including `inconclusive` when a budget or unavailable evidence prevents the requested check.

No high-match threshold automatically establishes meaning; sampled success is explicitly limited. No timeout/partial result becomes a complete check, zero mismatches or proof of no relationship. Comparing across stores/time periods is an authoring investigation choice and must appear in the receipt's actual scope, not as an invented claim of representativeness.

Core retains receipts using the project-controlled measured-evidence mechanisms; the final candidate receives bounded, credential-free evidence summaries/citations during deterministic finalization. The exact candidate binds these summaries. Model-authored IDs/counts are not accepted as measured proof: validation checks receipt existence, integrity, declaration and dependency identity. This is measurement provenance, not another knowledge registry or business-meaning approval store.

## 8. Automatic capture, confirmation and freshness

1. Read admitted/candidate pages, existing mapping hypotheses, schemas and source-linked domain evidence before rediscovering a rule.
2. Suggest a bounded candidate, obtaining the permitted shape summaries or documented examples needed to describe it.
3. Call core inspection; keep limitations, counterevidence and conflicting mappings explicit.
4. Automatically persist the hypothesis/evidence through the selected Git proposal's revision-checked page edit. Use stable concept/mapping IDs; repeated findings update the same hypothesis rather than creating suffixed duplicates. Identical content retries remain no-ops and cannot reset repair limits.
5. Ask the owner about unresolved meaning/format/scope. A failed/inconclusive inspection may still be saved as a labeled hypothesis; it cannot qualify an asserted mapping for execution.
6. Propose related Policy/OSI changes only when their meaning and scope are established. All existing compile/bind/grain/relationship gates apply; sample inspection is not a substitute for required live audits.
7. Review and stop for human admission. Restart preserves the proposal/hypothesis/evidence state; in-memory conversation persistence is neither required nor falsely claimed.

Changing schema, mapping parameters, source/lookup identity, scope or referenced Policy/OSI content invalidates dependent evidence when detected. A stale mapping cannot supply confirmed guidance without revalidation. Unversioned data is observed at a time, not permanently proven; do not claim universal drift detection or permanent validity from fingerprints/TTL. Retain existing required live relationship audits at validation/query boundaries. No continuous background scanner or per-query wiki write is introduced.

## 9. Admission, migration and scoped amendments

Context-only Git candidates may be human-admitted before a metric exists. Validate all applicable context/schema/source/evidence requirements. Semantic compile/bind/grain checks are marked **not applicable** only when there are genuinely no semantic declarations requiring them. Existing inherited semantic artifacts still undergo their applicable checks; page-only editing cannot skip them. Full matching admission evidence includes the applicability decision and exact candidate/source identity, never an unexplained partial report labeled complete.

A human reviews the exact final content/revision and any asserted mapping confirmations before activation. Known unsupported/conflicting assertions, fabricated evidence, stale source identity or mismatched candidate/review evidence refuse admission. Admitted investigative hypotheses stay non-authoritative. Existing source approval, coherent snapshot activation and previous-revision preservation remain binding.

No automatic renaming, reclassification, admission or history rewrite of existing artifacts. An explicit Authoring Proposal enriches legacy pages, preserves authored meaning, exposes schema changes, updates references/links and presents the complete diff. The plan must cover both legacy ingestion and new Git authoring callers; no pre-existing staged proposal is silently lost or treated as Git-reviewed. Historical date-only freshness fields remain readable while newly generated fields use the new datetime convention.

This revision makes bounded amendments:

- **ADR-0007 / authoring profile:** adds Dataset Overviews and general structured References; replaces mandatory six-category presence with applicable-page/dependency checks; permits unknown physical-table Grain without weakening semantic Grain; enriches schemas/citations/freshness.
- **Harness-led authoring / ADR-0013:** adds typed measured mapping inspection and automatic hypothesis edits, retaining source/document approval, bounded repair, core-owned evidence and human-only admission.
- **Modular-core/Git design / ADR-0016:** extends the previously excluded page types/format profile and missing-catalog behavior only for the new context capabilities; retains shared modules, proposal identity, source approval, finalized reviewed bytes and pinned serving.
- **Local Query/Context retrieval/Agent contracts:** adds term resolution, context-only discovery and the new Authoring inspection surface; preserves lexical search results, full metric/Policy caveats, numeric routes and fixed-role restrictions.
- **Standalone ingestion / ADR-0009:** preserves approved structured Reference metadata through its existing provenance/staging/review route, without auto-measuring or registering document-mentioned data sources or removing opt-in reconciliation.

The existing specification-0009 plan and published tickets are not changed by this approval. Their affected taxonomy, evidence, applicability, admission and adapter consumers must be reconciled by separately approved planning before implementation against the combined design. No new feature scope is silently appended to an old ticket.

## 10. Observable acceptance examples

1. **Same names, distinct assets:** two approved sources expose `orders`; generated pages/resources/bindings remain distinct through refresh, worktree changes and term resolution. A filename collision cannot overwrite the other asset.
2. **Schema/meaning refresh:** an unchanged column retains its explanation; a removed/renamed/type-changed column is flagged and its old meaning is not guessed onto another. Unknown metadata and sampled observations remain labeled; observed uniqueness/null counts do not become source constraints. Identical refresh leaves the candidate unchanged.
3. **Applicable bundle/context-only onboarding:** admit reviewed schemas/References for an approved source with no metrics, without fabricated Policies/skills/computations. Discovery/resolution works; a metric query reports no catalog. Introduce a model with unsafe Grain or a broken cited Policy: its applicable checks block admission even in a page-only candidate.
4. **Alias ambiguity and authority:** “order number” returns local/global alternatives with scope; “global order number” and exact qualified-column lookup find the intended representation. A word alias never authorizes a join. An admitted Reference containing a hypothesis still reports it as unconfirmed; an author-fabricated approval flag is not confirmation.
5. **Scoped identifiers:** ABC and XYZ both contain `123123`. Prefix/lookup inspection records two identities; proposed OSI never joins their plain numbers alone or fans out the root Grain. `00123`, unknown prefixes, variable-length ambiguity, prefix changes and documented reset scopes follow an established supported rule or remain unresolved.
6. **Measurement limits and authenticity:** a bounded high-match sample records eligible/tested counts, actual store/time scope and weak containment-versus-pairing basis. Timeout, missing lookup and incompatible types report error/inconclusive without success claims. Forged receipts/counts, unapproved asset references and attempts to raise operator ceilings fail; raw identifier examples are absent without sample permission.
7. **Autonomous durable hypotheses:** Authoring saves a new evidence-backed hypothesis without a per-save user prompt, then a new session reads it from the same proposal. Repeated discovery uses the same mapping identity; stale revisions, concurrent writers and interrupted transitions obey specification 0009 rather than overwriting/resetting evidence.
8. **Changed dependencies:** edit the source/schema/lookup/rule/Policy/OSI dependency; old dependent evidence cannot confirm the changed declaration. An unversioned live-source receipt remains explicitly as-of, with existing live semantic audits retained.
9. **Shared adapters and role boundaries:** Python/local CLI, optional Authoring/Analyst/Combined MCP and native roles observe the same core envelopes/refusals. Analyst has admitted-context resolution, not arbitrary mapping SQL; Authoring can inspect its proposal but cannot approve sources/admit it. A base install needs no MCP or Agent package for its local operations.
10. **Migration and preservation:** an explicit enrichment proposal preserves existing meaning/history/staged work and updates its links; no old files become admitted automatically. Existing retail numeric values, governed/ad-hoc labels, full caveats, independent-attestation distinctions and lexical passage-evidence checks still hold. Ordinary standalone ingestion retains its source provenance and opt-in reconciliation boundary.

New schema/terminology/inspection/context-only behavior requires focused failing-first regressions for the named scenarios during implementation; reuse existing numerical, grain, refusal and transport checks for preserved behavior. This documentation capture has an **existing-check** obligation: inspect owner-approved scope, source reconciliation, local links and the exact documentation delta. No runtime test, live inspection or passing implementation is claimed here.

## 11. Shaping capture and handoff

- **Vocabulary:** `CONTEXT.md` captures Dataset Overview, Schema Observation, Term Reference, Identifier Mapping and Mapping Evidence, and updates Bundle's relevant-page meaning. No data-project-specific order rule is promoted into Ariadne's repository glossary.
- **Decision:** ADR-0017 records one OKF authority with core-generated physical facts, sourced authored meaning, automatically retained hypotheses and separate exact-revision human confirmation, instead of a parallel registry or generic import/execution expansion.
- **Behavior:** revision 1 captures the approved in-chat design and examples above. Scoped cross-references reconcile the earlier contracts; their unaffected requirements remain binding.
- **Uncertainty:** written-specification review is complete; no material product choice remains for the approved scope. The implementation plan must define extension schema/version, identity encoding, typed request/receipt envelopes and finite operational/freshness limits, then reconcile affected specification-0009 interfaces/tickets without expanding these families or authority. Missing evidence/tooling returns to shaping rather than an unauthorized fallback.

Written capture approved by the owner, 2026-10-02. The subsequent “ticketzize” request authorized execution decomposition and GitHub ticket publication: [proposed plan revision 1](../plans/2026-10-02-0010-context-layer-schema-and-identifiers.md) maps interfaces/consumers to follow-up issues #41–#46 after #40, without expanding #32–#40's deliverables. Next gate: owner review/approval of the proposed execution map and separate implementation authority. Integration and code/release publication retain their own approval gates.
