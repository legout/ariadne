# Implementation plan: Context Layer schemas, terminology and identifier knowledge

| | |
| :--- | :--- |
| **Status** | **Proposed, revision 1 — owner review required; ticketized** |
| **Goal** | Extend the shared OKF profile with physical schema facts, scoped terminology, bounded mapping evidence and durable hypotheses, including context-only human admission. |
| **Behavioral source** | [Specification 0010, approved revision 1](../specs/2026-10-02-0010-context-layer-schema-and-identifiers.md). Owner approved the written revision with “approved.”, then requested “ticketzize” in the Pi conversation, 2026-10-02. The latter authorizes planning/decomposition and GitHub ticket publication, not approval of this plan or implementation. |
| **Architecture/vocabulary** | [ADR-0017](../adr/0017-context-schema-and-identifier-knowledge.md), [ADR-0016](../adr/0016-modular-core-git-authoring.md), [CONTEXT.md](../../CONTEXT.md). |
| **Predecessor** | [Specification 0009](../specs/2026-10-02-0009-modular-core-git-authoring.md), [its plan](2026-10-02-0009-modular-core-git-authoring.md), GitHub #32–#40. |
| **Contract** | planning-contract v1; installed skill provenance unknown. |
| **Task ownership** | GitHub issues [#41–#46](https://github.com/legout/ariadne/issues?q=is%3Aissue+in%3Atitle+%22Context+knowledge%22) own the canonical task bodies; this plan owns shared interfaces, dependency order, requirement coverage and global checks. |

## 1. Readiness, capture and reconciliation

Capture is complete: the approved specification owns behavior, CONTEXT.md contains the new terms, and ADR-0017 records the architectural alternatives and accepted constraints. Research remains evidence only. The serialization, envelopes and operational defaults below are proposed execution choices within that approved behavior; owner approval of this plan is still required before consumption. Material changes return to shaping.

Use one sequential writer. K1 starts only after the modular-core candidate in #40 is accepted, with an owner-accepted baseline and separate execution authority. This deliberately avoids interleaving two unapproved plans over the same files. #32–#40 keep their original deliverables; their completion does not claim specification 0010 is implemented. No reverse dependency from #40 to these tickets is introduced.

| Existing interface / owner | Follow-up owner and bounded amendment |
| :--- | :--- |
| #33 shared Context/Execution/Query; #35 source catalog/profile | K1: qualified asset identity and generated physical pages; preserve numerical query and legacy profile contracts. |
| #34 page identity/staging; #36 finalization | K1/K2: allow Dataset Overviews and general References, including them in the complete candidate/snapshot digest. Generated schema/evidence remain core-owned. |
| #35 approved evidence inputs | K3: finite typed inspection, shape summaries and verified receipts; retain resolved source and document permissions. |
| #36 full effective validation | K1/K2/K3/K4: applicable page contracts, extension/dependency validation and explicit semantic applicability. Never skip inherited semantic checks. |
| #37 exact human admission and pinned Query | K4: context-only admission and assertion-specific human confirmation; retain unchanged reviewed bytes, locking and atomic activation. |
| #38 role/toolsets and five-tool native Analyst baseline | K1/K2/K3: explicit authoring additions; K2 adds native Analyst `resolve_term` alongside its five existing tools. Analyst gets no inspection/edit/approval authority. |
| #39 legacy import/guidance; #40 installed verification | K6: explicit enrichment and updated instructions, preserved pending work and installed follow-up smoke. No automatic admission or legacy rename. |

The source documents are local/uncommitted. Tickets reference repository-relative paths and approved revisions, not nonexistent published commits. Obtain this matching source checkout before execution; issue publication does not authorize a commit/push. Preserve the existing dirty/staged/untracked work; no stash, reset or cleanup is authorized here.

Reuse Python >=3.12, DuckDB, SQLGlot, PyYAML and stdlib encoding/hash/timing tools. No dependency, backend, generic ontology, separate synonym registry, model-directed expression interpreter or second proposal store. Retain optional MCP and separately installed Agent packages. Execution remains supervised; verify builtin worker/reviewer availability before any later dispatch. Candidate assembly, target integration and code/release publication retain their explicit gates.

## 2. Shared concrete contracts

### Physical identity and generated content

A catalog asset carries `{source, catalog, schema, table}` with exact case-sensitive identifiers. `source` is the existing registry name. Attached-source `catalog` is its stable catalog name; file-view `catalog` is null rather than DuckDB's temporary in-memory catalog. Keep the actual schema/view namespace. Enumerate tables by the complete tuple, not table name alone: current `sources._catalog_entry` groups by table name, so same-named schemas require fixing the shared catalog and its profiling/discovery consumers together. Catalog/profile entries gain the tuple and resource; registry profile dictionary keys retain unambiguous legacy table names, using canonical table resources for same-source name collisions. Existing single-source/single-schema keys remain unchanged. Consumers use explicit identity fields, not parsing display names or profile keys.

Canonical resource payloads are JSON arrays: collection `[source, catalog, schema]`, table `[source, catalog, schema, table]`, serialized UTF-8 with compact separators and no ASCII escaping. Encode with unpadded URL-safe base64: `ariadne://collection/<payload>` and `ariadne://table/<payload>`. Never encode resolved file paths, DSNs, credentials or worktree locations. Approval/evidence separately binds the resolved source identity; a stable navigation resource cannot confer access after a registry change.

New generated filenames are `<source-slug>-<sha256(resource)>.md`: source slug replaces underscores with hyphens and is capped at 48 characters; the full lowercase digest preserves distinction after truncation. Check filename/resource consistency and duplicates before writing; a collision refuses instead of overwriting. Existing pages are not automatically renamed. Explicit enrichment can bind an existing page to an unambiguous asset while retaining its filename and links.

Dataset Overviews link the represented tables, not every approved source. Tables retain authored summary/column meaning outside the core-owned `# Schema` block and `ariadne.schema`/`ariadne.observations` metadata. Core schema entries include exact column identity/type and only supported declared nullability/default/comment/constraint information. Unsupported metadata is unknown. Observations record sample scope, counts, candidate keys, citation identity and explicit-offset `observed_at`; they do not declare business keys. A missing physical Grain is unknown; a declared one requires its cited authority. Semantic Grain requirements are unchanged.

Complete page edits may carry unchanged generated blocks; changed system-owned facts/approval/receipt claims are refused. Explicit refresh regenerates facts against approved inputs, preserves meaning only for identical column identity/type, and retains removed/changed explanations as reviewable history rather than guessing a rename. Finalization reuses matching observations and timestamps; identical inputs/content do not create a new commit.

### Structured References, authority and freshness

Supported `ariadne` extension version is integer `1`. Reject malformed supported fields, unsupported versions and author-supplied system authority. Legacy References without the extension remain readable; other existing governed extensions retain their contracts.

For structured References:

- `reference_role`: `term`, `identifier`, `enum` or `join`. Term/identifier roles use the representation/mapping structures below; this does not add standalone page types or an enum interpreter.
- `representations`: ordered objects with stable slug `id`, `aliases`, ordered `fields: [{resource, column}]`, required `scope: [{resource, column}]`, and optional cited description. Page-level `aliases` name the concept; representation aliases name a particular representation. Field identities are exact, not case-folded.
- `mappings`: objects with stable slug `id`, `family: equality|prefix|lookup`, `from`, `to`, the structured `candidate` below, `claim: hypothesis|asserted`, `source_ids` resolving actual page footnotes, and `receipt_ids`. No `approved`, `confirmed` or author-written measured counts/digests. Endpoint representation IDs must resolve within the Reference; related concepts use ordinary page links.
- Core finalization attaches verified dependency digests and bounded receipt summaries. Allowlisting an evidence ID is not proof: core must resolve it in the project's evidence records and verify declaration/dependency identity. Ordinary ingestion preserves allowed aliases/bindings and the actual input document's provenance; it cannot produce measured schema, receipts or confirmation.

Existing safe page-name validation governs concept/representation/mapping slugs. Reuse a matching concept/mapping ID; do not mint retry suffixes. Normalized candidate identity comprises family, ordered fields/components, scope and pairing/lookup parameters, not observed results or measurement time. Different/conflicting declarations remain separate labeled hypotheses; no last-write-wins reconciliation of meaning.

Generated schema/profile and mapping observations default to a 24-hour evidence age budget, configurable only by the operator outside candidate artifacts. Known schema, source approval, lookup, declaration, Policy or OSI dependency changes invalidate immediately. Receipt records include dependency kind/identity/digest; opaque data-version evidence is recorded only when supplied by the source. Unversioned data remains `as_of`, even within its age budget; after expiry or known dependency change it is `stale`. Unavailable freshness facts are `unknown`, never proof of currency. Freshness checks do not write pages during Query or replace live semantic audits. Domain statements track cited evidence/content revisions, not an invented universal data TTL. Historical date-only metadata remains readable; new measurements use explicit-offset datetimes.

### Typed public operations and role routing

All operations use the host-fixed project and shared core, JSON-shaped results, the existing payload/error conventions and revision safeguards. Local CLI operations work without MCP/Agent dependencies. CLI request files/stdin are adapter input, never model-supplied arbitrary filesystem destinations.

| Core operation | Request / result | Adapters |
| :--- | :--- | :--- |
| `AuthoringProject.refresh_schema` | Proposal ID, expected revision, explicit catalog asset list. Returns resulting revision, generated page identities and schema-change flags; approved reads and revision-checked writes only. | `ariadne-authoring refresh-schema`; `authoring_refresh_schema` in Authoring/Combined MCP; native Authoring. |
| `QueryRuntime.resolve_term` | Term or exact `{resource, column}` field lookup; bounded matches from pinned admitted context. Returns revision/admitted identity, concept/representation, bindings/scope, ambiguity, claim/confirmation/freshness and page/source citations. | `ariadne resolve-term`; Analyst/Combined MCP `resolve_term`; native Analyst. |
| `AuthoringProject.resolve_term` | Same query plus explicit proposal/revision; candidate identity stays visible. Read-only. | `ariadne-authoring resolve-term`; Authoring/Combined MCP `authoring_resolve_term`; native Authoring. |
| `AuthoringProject.inspect_mapping` | Proposal ID, expected revision, structured candidate and requested lower bounds. Returns a core receipt/error/inconclusive result, never a page edit or approval. | `ariadne-authoring inspect-mapping`; Authoring/Combined MCP `authoring_inspect_mapping`; native Authoring. |

Natural-language matching is deterministic casefolded whole-alias/phrase matching, not substring fuzzy inference. Limit to 20 matches by stable page/representation order, with explicit truncation and continuation using the existing bounded-read convention. Ambiguity reflects all eligible matches before truncation; never declare uniqueness from a truncated result. No match yields an empty match list. Malformed supported References and unauthorized/wrong revisions produce explicit errors. Resolver does not apply transforms, rewrite SQL or authorize joins; keep lexical `search_context` ranking, bodies and passage evidence unchanged.

### Inspection candidate and finite limits

The candidate is a discriminated JSON object, not an executable string:

- Common fields: `family`, ordered `left`/`right` field bindings, `scope` predicates and optional `pairing` field pairs. Scope operators are `eq`, `in`, `gte`, `lt`, using typed scalar values/finite lists bound as parameters. Pairing names independently supplied record keys, not a guessed row-order alignment; absent usable pairing is disclosed as containment-only evidence.
- Equality compares compatible scalar fields or equally sized composite tuples, including declared scope. Refuse lossy coercion; do not infer string identifier equivalence from numeric casts.
- Prefix uses ordered string component bindings and an explicit literal separator, compared to the target binding. An optional prefix lookup specifies an approved asset, ordered scoped key fields and one prefix-value field. No trim/pad/case-fold/suffix or freely interpreted formatting expression.
- Lookup specifies one approved lookup asset, ordered scoped key fields and ordered mapped-value fields, plus the participating left/right bindings. Report missing keys, duplicates and multiplicity rather than collapsing rows.

Operator defaults: at most 1,000 materialized sampled rows per participating asset, 20 seconds total inspection execution, 64 KiB serialized response, four participating assets, sixteen candidate field bindings and eight scope predicates (each `in` list at most 100 values). Optional raw examples cap at ten and require explicit operator sample permission; aggregate/shape output is the default. Requests can lower limits, never raise them. Resolver uses the same 64 KiB response ceiling. Reuse existing tighter payload/document limits. Large counts/scans are not made cheap by a result LIMIT: enforce the actual execution deadline using DuckDB interrupt/connection cleanup, disclose incomplete counts and refuse a backend operation whose cancellation cannot be bounded. Do not invent passing results for unavailable connectors.

Only requested candidates receive identifier-shape summaries, under the same access, sample and time limits. No all-pair exploration. Core validates every source/column, quotes identifiers and generates guarded read-only statements through shared Execution. Scope values are parameters. No public SQL/function/path field. The deadline covers source setup/catalog reads and inspection statements across all participating sources, using the owned connection's interruption and supported connector timeouts. If setup or execution cannot be bounded/cancelled for a participating source, refuse that inspection explicitly; never leave a background read running while claiming the request stopped.

A receipt contains core ID/integrity digest, normalized candidate/digest, proposal inspection revision, approved resolved source identities, asset/column/schema and lookup dependencies, observation time/version signals, scope/pairing basis, sampled/full designation, eligible/tested counts with unavailable counts explicit, null/missing/unknown-lookup counts, coverage denominators, mismatches, collisions, multiplicity, and `complete|inconclusive` outcome/limitations. Sampled completion means completion of the stated sample, not full-data proof. No high-match threshold asserts business meaning. Core retains it in the project-controlled evidence area with atomic persistence; finalized Git pages contain only bounded credential-free verified citations/summaries. Reuse the existing evidence mechanism, not a synonym registry or duplicate Git history.

Receipt dependency matching, not blanket candidate-commit equality, permits a measurement to survive the revision created by saving its hypothesis. Changed inputs/declaration invalidate it; unrelated page edits need not. Admission still binds the exact finalized candidate bytes, validation/review and source identity.

### Admission and automatic capture

Reports explicitly list applicable checks and `not_applicable` reasons. Context-only candidates omit semantic compile/bind/Grain only when no effective semantic declaration requires them. Inherited OSI, metrics, Policies and relationships still receive their checks. Unknown physical Grain never relaxes semantic Grain.

Review includes each asserted mapping's page resource, mapping ID, assertion digest, dependencies/evidence and confirmation eligibility. Human CLI admission accepts repeated `--confirm-mapping <reference-slug>:<mapping-id>` selections, displays their exact assertion content and requires explicit operator confirmation. Operational admission evidence binds those selections/digests to the exact reviewed revision. No selection means no new mapping confirmation; admitted hypotheses remain unconfirmed. Unchanged assertions retain matching prior human evidence only with unchanged verified dependencies; changed/stale/conflicting assertions cannot inherit confirmation. A plan-level or agent-authored approval flag is never sufficient. No MCP/native tool exposes confirmation/admission; activation does not mutate reviewed pages.

Authoring guidance first reads existing pages/evidence, inspects bounded candidates and automatically saves labeled hypotheses through `edit_proposal` at the returned/current expected revision, without a per-save prompt. It retains failed/inconclusive/conflicting results honestly, preserves stable IDs and repair history, and stops/refreshes on stale revision rather than replaying a write blindly. It asks the owner for unresolved meaning and uses OSI/Policy edits only after meaning is established. This is the existing agent loop plus core tools, not a second background engine. Session restart reads Git/evidence state; chat memory is not claimed durable.

## 3. Dependency order and canonical task index

```text
#40 accepted → K1 → K2 → K3 → K4 → K5 → K6
```

K1–K4 define public/data/authority contracts: high risk, immediate read-only review before consumption and one eventual candidate review. K5 uses those accepted contracts: normal risk and candidate review. K6 includes explicit migration: high risk, immediate delta review of migration plus candidate integration review without reopening settled findings. Parent owns dispositions and repairs; at most one authorized fix pass and one delta-only recheck. Fresh reviewer prompts must paste the guardrails/orchestrator contract, actual criteria, written conventions and real-use context. No reviewer is launched by ticketization.

| Unit | Deliverable | Prerequisite | Test obligation |
| :--- | :--- | :--- | :--- |
| [K1 / #41](https://github.com/legout/ariadne/issues/41) | Qualified schema facts and deterministic explicit refresh through shared callers | #40 accepted; plan approval, accepted baseline and execution authority | `new-test` |
| [K2 / #42](https://github.com/legout/ariadne/issues/42) | Structured References, standalone-ingest preservation and scoped read-only resolution across roles | K1 accepted | `new-test` |
| [K3 / #43](https://github.com/legout/ariadne/issues/43) | Permission-bound equality/prefix/lookup inspection, shape evidence and authentic receipts | K2 accepted | `new-test` |
| [K4 / #44](https://github.com/legout/ariadne/issues/44) | Context-only validation/admission and exact-assertion human confirmation/freshness | K3 accepted | `new-test` |
| [K5 / #45](https://github.com/legout/ariadne/issues/45) | Automatically retained, restart-readable mapping hypotheses in native Authoring | K4 accepted | `new-test` |
| [K6 / #46](https://github.com/legout/ariadne/issues/46) | Explicit legacy enrichment, guidance and installed candidate verification | K1–K5 accepted; candidate-assembly approval | `new-test` for enrichment; `existing-check` for candidate validation |

## 4. Requirement coverage

AC references are specification 0010 §10's numbered examples. Tickets own exact files, checkbox steps, failing-first scenarios and focused commands; this table does not duplicate task bodies.

| Source | Tasks / evidence |
| :--- | :--- |
| §§1–2 one OKF/core authority, shared ownership and unchanged execution boundaries | K1–K5 use predecessor interfaces; K6 installed/parity/preserved-semantic checks |
| §3 applicable pages, Dataset Overviews, unknown physical Grain and standalone References | K1 generated pages/per-type gate; K2 ingestion; K4 applicable full validation |
| §4 qualified identity, observed-versus-declared schema and deterministic refresh | K1 same-source/schema and cross-source identity/refresh regressions; K6 explicit legacy enrichment |
| §5 scoped aliases/representations/mappings, OSI ownership and confirmation | K2 structured References/resolution; K3 family inspection; K4 human assertions |
| §6 admitted/candidate resolution, ambiguity, fixed roles and context-only discovery | K2 all resolver adapters; K4 no-model admitted snapshot; K6 preserved retrieval checks |
| §7 typed finite inspection, sample permissions, scope and receipt authenticity | K3 inspection/timeout/refusal regressions; K4 receipt-bound admission |
| §8 automatic persistence, stable IDs, dependency freshness and restart | K5 native save/restart regression; K3/K4 dependency/evidence checks; predecessor concurrency checks reused |
| §9 human context-only admission, inherited checks and explicit migration | K4 authority/applicability refusals; K6 preserved legacy pending work |
| AC1–2 | K1 collisions, observed metadata and unchanged/changed-column refresh |
| AC3 | K4 context-only positive path and inherited unsafe semantic declarations |
| AC4 | K2 alias alternatives and qualified lookup; K4 hypotheses versus confirmed assertions |
| AC5–6 | K3 scoped ABC/XYZ/leading-zero/lookup cases, finite limits and receipt authenticity; existing semantic fanout checks retained |
| AC7 | K5 automatic capture, identical retry and restart; predecessor stale/concurrent/interrupted checks |
| AC8 | K3/K4 dependency invalidation and explicitly as-of unversioned evidence |
| AC9 | K1–K3 thin adapter parity/roles; K6 installed core without optional packages |
| AC10 | K2 ingestion provenance/opt-in reconciliation; K6 migration plus existing numbers/caveats/retrieval/attestation checks |

## 5. Global validation and handoff

Reuse the predecessor plan §6 baseline/candidate commands, once per baseline and assembled candidate, not per checkbox. There is no new CI framework. Each new behavior starts with the ticket's one named failing-first public-seam scenario; use focused variants only for distinct reachable defects. Reuse existing numerical/Grain/refusal/retrieval/transport checks instead of creating another numeric oracle.

Candidate evidence must include built-wheel local operations without MCP/Agent, optional stdio registries with the accepted extras, and native fake-provider Authoring/Analyst checks. Fake-provider results do not prove live-provider compatibility. Optional live connector/provider checks require approved endpoints/credentials and are reported separately; unavailable converters/connectors are disclosed, not silently substituted. Probe supported changed paths actively with LSP and inspect the final diff.

Real use: host-fixed local Python/JSON CLI, stdio MCP, fixed native Agent roles, operator-approved sources/documents/sample permissions, and model-authored page/candidate inputs. Future touched boundaries are catalog identifiers/scope reaching guarded Execution, model claims reaching evidence validation, and complete page edits reaching Git/admission. Assets are approved data/identifier samples and proposal/admitted bytes; reachable defects include unauthorized reads/raw samples, fabricated receipts/confirmation and stale or conflicting revision activation. Trusted user files/operators are not attackers; no stolen-secret, broken-TLS or malicious-admin scenario is invented. Ticketization itself changes documentation/tracker content only: security n/a.

Residual risks: source adapters' metadata/cancellation capabilities, preserving profile consumers while distinguishing schemas, generated-content ownership in complete edits, receipt validity across the save commit, legacy ambiguous bindings, and the deliberately sequential predecessor dependency. Resolve a capability failure explicitly before its dependent task; do not add a connector, raw SQL fallback or authority bypass.

**Handoff:** six GitHub tickets (#41–#46) are published at the owner's request, with K1 blocked by #40 and each later slice blocked by its predecessor. Plan revision 1 remains proposed; ticket publication does not approve the plan or authorize implementation. No runtime tests, inspections, implementation, commit/push, integration or release are performed by this planning task. Approve the execution map separately before dispatch.
