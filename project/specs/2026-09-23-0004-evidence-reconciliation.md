# Specification: Opt-in document evidence reconciliation

| | |
| :--- | :--- |
| **Status** | **Approved** |
| **Approved by** | Owner, pi session 2026-09-23 — complete design and written specification approved: ingest first, exact-path identity, explicit opt-in LLM advisory, human promotion gate |
| **Scope approved** | Revision 1: opt-in re-ingestion comparison of document-derived Context Layer proposals against approved pages, source-linked change preview, advisory possible-conflict quotes, and safe staging; no author-loop or promotion automation |
| **Decisions** | [ADR-0009 standalone ingestion](../adr/0009-standalone-proposal-first-ingestion.md) and [ADR-0003 review gate](../adr/0003-staging-dir-review-gate.md), clarified for single-user real documents by the same owner |
| **Evidence** | [ktx/nao/OmniGraph comparison, recommendation 3](../research/2026-09-23-ariadne-ktx-nao-omnigraph-comparison.md); existing [`ariadne.ingest`](../../src/ariadne/ingest.py) and [`ariadne.promote`](../../src/ariadne/promote.py) |
| **Contract** | planning-contract v1; installed skill provenance unknown |

## Purpose and boundary

Re-ingesting a revised document currently stages a newly named page (with collision suffix if needed) without comparing it to a published, possibly human-edited Policy. A human could promote a duplicate or replace a rule without seeing what changed. The first improvement is a **single-user, explicit review comparison** on the document ingestion path, using the existing OKF `sources[]` provenance and human Promotion gate. The Authoring Agent's full-bundle regeneration remains unchanged.

For single-user real documents, staging and explicit human Promotion remain the accepted gate (ADR-0009 and the clarified ADR-0003). A PR gate becomes necessary for multi-author or asynchronous approval; this feature does not implement it. No path automatically promotes, edits an approved page, or changes an OSI metric.

## Opt-in interface and identity

- Existing `ariadne-ingest <doc>...` and `ingest(docs, staging_dir=..., complete=...) -> (staged_paths, errors)` retain their behavior and do not read or send any approved Policy to a model. The opt-in CLI form is `ariadne-ingest --reconcile --served ROOT <doc>...`; `ROOT` must contain `context_layer/`. Missing or invalid `--served` fails before model calls or staging writes. An additive `reconcile_ingest(docs, *, served_root, staging_dir="staging", complete=None) -> (staged_paths, errors, comparisons)` entry point exposes the same opt-in mode; its comparison records carry the proposal path, match status, old/new source reference and digest, change classification, and advisory status. Default API return shape does not change.
- A proposed page matches an approved page **only by the same Context Layer-relative path** and compatible source identity: at least one approved `sources[].resource` identifies the same input document as the new proposal. A changed source-byte digest is an expected revision, not an identity mismatch. Normalize paths for comparison without allowing a proposed or symlinked path to read outside the selected approved Context Layer. Treat existing `sources[].resource` values as identity strings, not paths to open during reconciliation. Do not use model-generated titles or fuzzy matching to select an approved target.
- A same-path approved page with no compatible source reference is an identity conflict: report the path and source mismatch, stage nothing for that document, and require operator resolution. If the proposal has a different path but a potentially matching source/title, warn of a possible duplicate while staging it as a **new** page; do not silently retarget it. A new page with no plausible match follows the normal proposal path.

## Compare, advise, stage

For each document, run the existing conversion, LLM distillation, credential refusal, per-type gate, and staging containment checks. Before writing any of that document's proposals, resolve their candidate paths, source matches and collisions. This comparison is **not** a new semantic correctness gate.

- Compare approved and proposed page content with promotion bookkeeping (`status`, `verified`, generation timestamp) separated from the owner's title, description, tags, body, and source provenance. An identical page with the same source digest is `unchanged` and stages nothing. A changed source digest with unchanged rule text is a visible **provenance-only** update and stages the corrected source citation. A changed rule or page metadata is `changed` and stages a proposal at its exact approved relative path; show a bounded human-readable diff and both source references/digests. Any matched Policy is human-owned for review regardless of its `generated.by` value.
- Do not overwrite an already staged proposal. In reconciliation mode, an existing staging path for an approved replacement is an error for that document, **not** a `-2` replacement with a different page identity. Preflight identity and collision failures across all proposals from one document before staging any of them; other documents in the same invocation remain independently processable. Unmatched new pages retain the existing collision-safe staging behavior, with any final suffixed path reported explicitly.
- Only after a matched approved **Policy** has changed body text may the explicitly opted-in path make an additional call through the existing configured ingestion model. Before that call, apply the existing credential-pattern refusal to the approved Policy text: if it appears to contain a credential, do not send it; keep the deterministic diff and report advisory `unavailable` without echoing the suspected secret. Otherwise send the converted input and only the relevant approved Policy title/body and source identity, not its `verified` identities or unrelated Context Layer pages. The model may suggest a *possible conflict* with quoted passages from both texts. Verify each quote is present verbatim in the converted document or approved page before displaying it as supported. Unsupported quotes are `unverified`, not evidence; an absent suggestion is never proof of consistency. Provider failure leaves the deterministic comparison visible, marks advisory `unavailable`, and does not by itself prevent safe staging.
- The comparison and any advisory appear in the opt-in command's review output and additive Python result, not in served pages, generated `index.md`/`log.md`, or an extra ledger. A model suggestion never sets `review_needed`, approves, blocks, or silently rewrites a Policy. A changed Policy requires the operator to review the actual staged page and diff before the existing `ariadne-promote` confirmation; `--yes` retains its existing explicit human-use semantics.

Existing `sources[]` entries carry document resource and digest; no new OKF schema or secondary graph is introduced. On human Promotion, the source citation updates along with the approved page through the existing merge and verification bookkeeping.

## Failure, migration, and acceptance

Default ingestion, its per-type validation, no-secret staging checks, collision suffixes for ordinary ingestion, and the current `promote` interface remain unchanged. An invalid approved root, escaped/symlinked target, identity mismatch or replacement-path collision fails before any proposal from that document is staged; no served file is written. A failed advisory never erases a deterministic diff and is reported as such. No migration of existing bundles is required; an approved page without a compatible source identity requires explicit human resolution rather than an inferred match.

Acceptance examples:

1. Ingest a document, promote its Policy, edit the served Policy as a human, then re-ingest a revised document using `--reconcile --served`. The served edit stays byte-identical; the staged proposal targets the same relative path, carries the new source digest, and the review output shows old/new source references, the rule diff, and any supported or unverified model suggestion. Only later human Promotion may replace it.
2. Repeating identical input and identical proposed content stages no replacement; changing only the source bytes while keeping the Policy text stages a provenance-only proposal. A different LLM rendering of the same source remains a visible content change, not a silently accepted repeat.
3. A candidate with a renamed path but similar source/title emits a duplicate warning without claiming the old path; a same-path, different-source candidate or an already occupied replacement staging path stages nothing for that document.
4. An advisory failure, a credential-pattern match in an approved Policy, or an invented quotation is visibly unavailable/unverified as appropriate while the validated deterministic comparison remains available; the approved Policy is not sent when its text matches a credential pattern. The model cannot change the decision made by `ariadne-promote`.
5. Ordinary `ariadne-ingest` continues to stage new pages without a served-root requirement or sending approved Policies to its model, and the existing `ingest()` callers keep the same return shape.

## Shaping capture checkpoint

- **Vocabulary:** Existing Policy, Context Layer, Staging, and Promotion terms in [`CONTEXT.md`](../../CONTEXT.md) suffice; change classifications and model suggestions are operational output, not new canonical domain terms.
- **Decisions:** Explicit Policy egress instead of default disclosure or no model comparison is a consequential trust-boundary choice, captured as a clarification of ADR-0009. Single-user staging for real documents instead of an immediate PR gate clarifies ADR-0003. Both were explicitly approved by the owner; neither changes the human-only Promotion invariant.
- **Behavior:** This approved revision owns opt-in scope, matching, comparison, advisory, failure behavior and acceptance. Design approval does not authorize implementation, integration or publication.
- **Uncertainty:** Semantic conflict identification is fallible advisory evidence, not an unresolved approval decision. A source identity mismatch requires an operator choice in the specific case, not automatic inference.
