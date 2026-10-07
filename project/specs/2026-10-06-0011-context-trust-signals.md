# Specification: Advisory Context trust and lifecycle signals

| | |
| :--- | :--- |
| **Status** | **Approved, revision 2 — workflow-policy amendment; behavioral scope unchanged** |
| **Workflow amendment approval** | Owner requested “can you execute the recommende migration for me?” in Pi session `01a115c0-1a8b-7099-87c3-df0aa8d87abc`, 2026-10-07, after the workflow audit. This approves the workflow-policy/source-handoff amendment and existing issue updates only; feature implementation, source/report acquisition, candidate assembly/integration, deployment, commits/pushes and releases remain separately gated. Original revision-1 approvals below remain historical provenance. |
| **Approval** | Owner, Pi conversation 2026-10-06: requested `shape-design` for the OKF trust analysis; selected advisory signals, metadata plus brief answer caveats, concrete warning triggers, already-consumed dependencies, and readers/disclosure only. Subsequently replied “approved” to the complete seven-section in-chat design revision 1 and its documentation-capture boundary. This approves the design, this specification's capture, vocabulary and scoped source references. The owner subsequently approved this written revision with “approved” after receiving the captured specification path, opening implementation planning only; not implementation, integration, ticket changes or publication. |
| **Scope** | Correct freshness interpretation; additive shared Context signals and dependency warnings; brief relevant answer caveats; precise attestation terminology. |
| **Sources** | [Research](../research/2026-10-06-okf-v02-trust-signals.md), [schema/terminology specification 0010](2026-10-02-0010-context-layer-schema-and-identifiers.md), [modular-core/Git specification 0009](2026-10-02-0009-modular-core-git-authoring.md), [Context retrieval](2026-09-23-0002-context-retrieval.md), [context-carrying answers](mvp-vertical-slice.md), [ADR-0007](../adr/0007-okf-bundle-structure-agent-generation.md), [ADR-0011](../adr/0011-context-carrying-answers-and-skill.md), [ADR-0016](../adr/0016-modular-core-git-authoring.md), [ADR-0017](../adr/0017-context-schema-and-identifier-knowledge.md), [vocabulary](../../CONTEXT.md). |
| **Contract** | planning-contract v1; installed skill provenance unknown. |

## 1. Purpose and boundaries

Make existing OKF trust and lifecycle evidence deterministically interpretable and visible to Ariadne consumers. Correct the reader gap demonstrated by the research: valid explicit-offset expiry timestamps currently become `unknown`. Expose warnings for concrete problems in context actually consumed by an operation, rather than expecting each agent or adapter to interpret frontmatter independently.

The owner selected advisory disclosure over a parser-only correction or enforced lifecycle filtering/refusal. Keep the shared Context/Query architecture, full business-rule text and exact-revision human admission. Document verification, freshness, admission and independent numerical validation are distinct claims.

Non-goals: producer-output or expiry-duration changes; artifact migrations/restamping; recursive dependency traversal; external-source fetching; new tools, permissions, services, stores or dependencies; trust/credibility scores; search filtering or ranking changes; query refusal based solely on these new warnings; automatic approval; changes to metric arithmetic, compilation or live semantic audits; the OKF executor/receipt ABI; arbitrary executor scripts; per-run attestation implementation; ticket changes, implementation, integration or publication.

This specification owns the additive consumer extension. It does not rescind specification 0010's producer timestamp requirements, alter mapping-evidence age policies, or reopen its schema/identifier design.

## 2. Shared interpretation and operation flow

The existing shared Context module owns page trust/freshness interpretation. Query and Authoring use that interpretation for their existing operations; Python/CLI, applicable MCP toolsets and native Agent adapters preserve the resulting envelopes without a second interpretation implementation.

An operation retains its existing admission, revision, source and containment checks. It reads its existing eligible context pages, captures one aware UTC clock value for their assessments, creates the shared advisory view, and returns it alongside the existing result. No warning bypasses an existing refusal. No signal grants SQL, join, transform, source-access or admission authority.

The clock is observational: subsequent reads may cross an expiry boundary, but neither read changes an artifact, expiry, admission record or validation state. Retries have no new mutable state. No new source or linked-page read is introduced beyond §5's consumed set.

## 3. Freshness semantics

Support ISO 8601 date/datetime strings and YAML-native date/datetime values, normalized for JSON disclosure without rewriting source bytes.

- **Explicit-offset datetime:** compare aware instants. State is `stale` when `now >= stale_after`, otherwise `current`. `Z` and equivalent numeric offsets are supported; the same instant has the same state regardless of its expressed offset.
- **Historical date-only value:** preserve the established UTC calendar-day convention. It remains `current` throughout the named UTC date and becomes `stale` at the next day's midnight. This is compatibility handling, not the timestamp convention for new producers.
- **Absent, malformed, unsupported or timezone-ambiguous value:** state is `unknown`. Never infer UTC for a naive datetime or infer currency from a missing fact.

The disclosed freshness view retains `state` and `stale_after`. Supported YAML-native values become ISO strings; an invalid textual expiry remains visible as text with state `unknown`; an absent value is null. Do not confuse a parse failure with proof that the page is current.

Existing term-match `freshness` fields receive this correction and stay present. Mapping receipts retain their separate `as_of`/`stale`/`unknown` evidence-age semantics, dependency checks and confirmation-withholding behavior. A page's current expiry cannot restore a mapping confirmation over stale evidence. Neither form of freshness proves current live-data correctness.

## 4. Additive response contract

Add a JSON-shaped `context_signals` envelope containing `pages` and `warnings`:

- Each `search_context` hit receives the envelope for that returned page.
- Each term-resolution match receives the envelope for its matched Reference, including Authoring's existing candidate resolver. Existing match freshness, sources, representation identity, ambiguity, claim/confirmation fields and revision/admission provenance remain present.
- Each governed metric's existing `context` block receives the envelope for its consumed pages. This covers `get_metric` and each metric's context within `query_metrics` wherever those operations already exist; it does not add operations to a fixed-role toolset.

Each assessed page identifies its bundle-relative `path` and exposes lifecycle `status`, `freshness`, advisory `verification_tier`, and available `generated`, `verified` and `sources` evidence. Preserve actual source identities and objective source signals; do not invent authors, timestamps, usage counts or confirmations. Missing optional evidence remains explicitly absent/unknown.

For a readable concept, absent lifecycle status uses OKF's `stable` default. Preserve applicable declared statuses, including existing Ariadne draft/review states; malformed lifecycle metadata is unknown, not implicitly stable. Reserved navigation/history files without concept frontmatter do not become business definitions or acquire invented verification evidence.

Verification tiers are `unverified`, `machine-confirmed` and `human-reviewed`, derived conservatively from usable document verification declarations. No usable confirmation, including an empty list, yields `unverified`; non-human confirmations only yield `machine-confirmed`; a declared human confirmation yields `human-reviewed`. This is advisory disclosure of document claims, not authentication or admission evidence.

Admission route/revision evidence remains separate. An admitted page lacking `verified` still has its genuine admission provenance; never derive admission from a `human:` actor string or synthesize a document-verification entry from admission.

Warnings identify the affected bundle-relative path and one of the stable codes in §5. Multiple problems may apply to a page. Preserve full page bodies, passage pointers, ranking/eligibility, staged-root `draft` labeling, rows, SQL, lineage, governed/ad-hoc labels and existing admission fields. Page status is not a replacement for staged/admitted identity.

Term responses retain their existing limits, continuation and explicit-elision behavior. If metadata is omitted under those limits, disclose that omission; a missing/elided warning list must not be represented as a complete assessment with no warnings. Existing ad-hoc `context: null` remains unchanged. No separate metadata-only replacement for rule text is introduced.

## 5. Consumed dependencies and failures

Assess only the already-consumed set:

1. The returned search or matched Reference page.
2. A governed metric's own page and directly cited Policy pages.
3. Its associated computation page, when read by the existing computation-context path.
4. Mapping evidence already assessed by the existing resolver, preserving that evidence's existing rules rather than traversing new dependencies.

Do not recursively follow table, Reference, Policy or Markdown links. Do not fetch a `sources` resource or execute a computation resource. Existing project/root selection and containment restrictions continue to bind every local read.

Warning codes:

- `context_stale`: a consumed page's supported expiry has been reached under §3.
- `context_deprecated`: a consumed page explicitly declares deprecated lifecycle status.
- `context_unavailable`: required metric/Policy context is missing or unreadable through the existing context-assembly path.

Absent/invalid optional expiry, generation or verification metadata produces an unknown/unverified signal, not a warning by itself. A draft remains labeled through the existing draft/claim rules; it does not become approved through document metadata. An absent optional computation does not create a new query failure or required-context warning.

Required-context failures retain the current non-failing null/empty fallback and add the relevant warning; do not invent rule text, unavailable dependencies or successful assessments. If the metric page cannot be read, its undiscoverable Policy dependencies are not claimed to have been assessed. Existing admission/snapshot/source/compile/live-audit errors still refuse as before: only these newly disclosed lifecycle/context problems are advisory.

Warnings do not filter search hits, refuse otherwise valid queries, change values or convert a governed result into an ad-hoc one. `governed: true` continues to mean human admission, not fresh evidence or independent numerical validation.

## 6. Answer caveats and attestation vocabulary

Packaged workflow guidance and applicable native Agent guidance require a brief caveat when an answer actually relies on warned context. Identify the relevant issue and Policy/page instead of printing every signal. An unrelated search hit, or missing optional verification/expiry alone, does not trigger an answer caveat.

For example: “This uses the admitted definition, but its cited revenue Policy has expired.” Preserve existing governed/ad-hoc distinctions, actual rule caveats, draft/hypothesis restrictions and pending independent-validation disclosures. Metadata cannot override the user's question, served rules or runtime gates. Adapter/tool permissions are unchanged.

Keep these claims distinct in vocabulary and consumer guidance:

- **Definition admission:** human review of the exact effective artifact revision through its applicable route.
- **Document Verification:** confirmations declared against a document's sources; advisory metadata, not admission.
- **Execution Attestation:** per-run sanctioned-execution provenance and fidelity between the reported value and authoritative execution result; not implemented by this revision.
- **Independent Numerical Validation:** comparison with an independent expected-value source, distinct from execution fidelity.

Preserve current fields and the Ariadne application-profile meaning of `Attested Computation`. `attestation: pending` continues to disclose missing independent numerical validation. A compiler pass, human admission or stored `attester` reference is not a successful current-run execution verdict, and a stored test reference does not prove each current answer was numerically checked. No computation type/field rename or new executor/attester ABI is introduced.

## 7. Migration and preservation

This is reader/disclosure work, not producer or artifact migration. Keep existing generated expiry values/durations, computation generation, proposal finalization and admission bookkeeping unchanged. Do not restamp legacy pages or modify an admitted Git revision after review.

The envelope is additive; old response fields and their non-metadata payloads remain intact. Existing page and source formats remain readable. No new tool, snapshot history rewrite, knowledge store or continuous freshness scanner is introduced. Existing context-only discovery, missing-catalog errors, role boundaries, numeric routes and mapping confirmation behavior remain binding.

## 8. Observable acceptance examples and validation

1. **Instant interpretation:** an expired/future explicit-offset string and its YAML-native aware datetime receive the expected state and a disclosed expiry. Equivalent `Z`, positive-offset and negative-offset instants agree; at exact expiry state is stale.
2. **Legacy and unknown values:** a date string/native date stays current on that UTC date and becomes stale the next day. Absent, malformed and naive-datetime values remain unknown without inventing a date or generating an optional-metadata warning.
3. **Policy warnings without changed arithmetic:** a metric citing an expired/deprecated Policy returns the same rows/SQL/governed label and full successful context bodies, with the applicable path-specific warnings. The same shared interpretation reaches existing adapters and multi-metric contexts.
4. **Missing required context:** where the existing context path permits a non-failing missing/unreadable metric/Policy fallback, it remains non-failing and discloses `context_unavailable`. No missing rule or undiscovered dependency is fabricated; source/snapshot admission refusals still bind.
5. **Independent authority axes:** a genuinely Git-admitted page without document verification remains admitted and reports unverified document signals, with no fabricated verification entry or missing-optional warning. A staged page with a declared human actor remains staged and non-authoritative.
6. **Bounded discovery:** a deprecated served hit retains its old rank, body, passage pointers and `draft: false` alongside its advisory status/warning. Term matches retain ambiguity, field/source identity, freshness and confirmation behavior; oversized metadata uses explicit elision/continuation without false completeness.
7. **Evidence and dependency boundary:** stale mapping evidence still withholds current confirmation even when the Reference page's expiry is current. Operations do not recursively read linked pages or fetch source URLs, and missing optional computations add no new failure.
8. **Relevant conversational disclosure:** an observed Agent answer relying on an expired Policy states the brief caveat without changing the computed number or claiming independent/runtime attestation. An unrelated stale search hit or absent optional metadata alone adds no spurious answer warning.
9. **Read-only compatibility:** repeated reads, including a read crossing expiry, do not change any artifact, expiry, proposal, admission or validation record. Legacy producer output, Git finalization and role/tool permissions remain unchanged.

Implementation obligations: **new-test** for the named freshness/disclosure scenarios, with expectations derived independently from §3 and the acceptance examples; **existing-check** for preserved numeric, retrieval, adapter, admission and mapping-evidence behavior. The existing explicit-offset bug requires a reproducing test that demonstrably fails before its correction; behavior-affecting refactors require characterization before mutation. Ordering for new disclosure/guidance behavior is the worker's choice. Guidance changes require refreshed observed Agent evidence, not mechanically edited trace digests. The implementation plan owns task decomposition and exact commands; this specification does not authorize running implementation or live-data checks.

This documentation capture has an **existing-check** obligation: compare the approved scope, inspect the documentation delta and verify local links. No runtime implementation, test-suite pass or deployed behavior is claimed.

## 9. Capture checkpoint and handoff

- **Vocabulary:** Freshness, Document Verification, Execution Attestation and Independent Numerical Validation are captured in the single-context [CONTEXT.md](../../CONTEXT.md). Existing application-profile Computation terms are clarified without changing their current runtime meaning.
- **Decisions:** no new ADR is warranted. The selected advisory behavior is reversible and preserves the accepted architecture/authority boundaries; cross-reference this extension from the affected existing source records rather than manufacturing a new architectural decision.
- **Behavior:** this revision owns the approved scope, non-goals, interfaces and acceptance examples. Research remains supporting evidence, not an execution source.
- **Uncertainty:** the material shaping choices are resolved and written revision 1 is owner-approved. Its implementation plan revision 1 is also owner-approved; execution authority is not implied.

Planning-contract v1; original installed skill provenance unknown. Behavioral revision 1 remains approved; revision 2 adds only the owner-approved 2026-10-07 workflow-policy amendment. The [implementation plan](../plans/2026-10-06-0011-context-trust-signals.md) is approved at revision 2 by that same scoped amendment, preserving the original planning approval. No existing feature scope is expanded; later implementation, source access, assembly/integration, deployment and publication retain their applicable approval gates.
