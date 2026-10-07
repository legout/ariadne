# OKF v0.2 trust signals: implications for Ariadne

Research date: 2026-10-06. **Evidence and recommendations only; not implementation approval.**

## Recommendation

**Keep Ariadne's architecture. Improve how existing consumers interpret and disclose trust metadata.** The article describes a version Ariadne already adopted, not a reason to replace OSI, the compiler, human admission or the Context Layer. The next bounded round should correct freshness interpretation and expose consistent lifecycle/provenance warnings. Clarify the distinction between OKF execution attestation and Ariadne's independent numerical checks. Defer a full portable executor/attester ABI until there is an actual interoperability or audited-answer consumer.

## Sources and scope

- [Google Cloud article, “Open Knowledge format v0.2 tackles agentic trust,” July 25, 2026](https://cloud.google.com/blog/products/data-analytics/okf-v0-2-adds-trust-signals).
- [Canonical OKF v0.2 specification](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/0b87c52c6ef999286c745e19998fdfcd03d5dbee/SPEC.md), particularly §§5, 7, 10–11 and 13. Revision `0b87c52c6ef999286c745e19998fdfcd03d5dbee` is the latest SPEC-changing commit returned by GitHub during this investigation.
- [Acme revenue computation](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/0b87c52c6ef999286c745e19998fdfcd03d5dbee/bundles/acme_retail/computations/revenue-ytd.md), [BigQuery executor instructions](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/0b87c52c6ef999286c745e19998fdfcd03d5dbee/bundles/acme_retail/skills/run-on-bq.md), and [reference SQL attester](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/0b87c52c6ef999286c745e19998fdfcd03d5dbee/bundles/acme_retail/attesters/sql_equality.py). These illustrate the contract; their presence does not independently establish production correctness.
- Current Ariadne source at checkout `ab8c0377f992db4857678420b3022560c01d2532`, its accepted ADRs, and focused synthetic probes. No live business data, Google SQL or downloaded attester code was executed.

The article links the old `knowledge-catalog/okf` location. Its [README now redirects consumers](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/README.md) to `GoogleCloudPlatform/open-knowledge-format`; use the canonical repository for future references.

This follows [the October 2 OKF/schema investigation](2026-10-02-context-layer-okf-and-identifiers.md), but assesses the now-present shared Context/Query and Git-admission implementations rather than treating that earlier note's implementation inventory as current.

## 1. What the article adds—and what it does not

**Trust:** `generated` identifies production of current content; `verified` records confirmations against its sources. Consumers derive unverified, machine-confirmed or human-reviewed tiers, with `human:` identifying human actors. These are advisory signals, not authorization or proof that the current data is correct. OKF §11 permits concepts with absent optional trust metadata; Ariadne's governed execution still has its separate application admission requirements.

**Provenance:** `sources` identifies actual evidence, with stable IDs for claim-level Markdown footnotes. Optional `author`, `usage_count` and `last_modified` are objective signals. OKF deliberately does not prescribe a portable credibility score. Usage does not establish business correctness.

**Lifecycle:** `status` distinguishes draft, stable and deprecated content. The canonical specification defines `stale_after` as an explicit-offset ISO 8601 instant, stale when `now >= stale_after`. The blog uses date-only examples and looser next-day language; use the specification for new timestamp semantics and preserve legacy date handling explicitly rather than silently reinterpreting old artifacts.

**Attestation:** an `Attested Computation` declares a sanctioned computation, parameters, executor receipt and deterministic attester. Per-run attestation checks that the sanctioned computation produced the result and that the displayed value matches the authoritative execution result. It is distinct from reviewing the definition, and it is **not an independent expected-value oracle**. A sanctioned but obsolete definition can attest successfully; lifecycle checks remain necessary. [OKF §10.5–10.6](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/0b87c52c6ef999286c745e19998fdfcd03d5dbee/SPEC.md)

## 2. What Ariadne already does well

- **Already adopts v0.2.** [ADR-0007](../adr/0007-okf-bundle-structure-agent-generation.md) accepts typed pages, generated navigation/history, sources, generation, verification and lifecycle metadata. Its later amendments retain honest pending numerical attestation and pre-review finalization for Git authoring.
- **Admission is stronger than a frontmatter assertion.** Staged Promotion is human-owned. The Git route validates/reviews exact final bytes and serves a pinned admitted revision, with admission evidence outside those bytes. [ADR-0016](../adr/0016-modular-core-git-authoring.md); [QueryRuntime admission view and pinned checks](../../src/ariadne/query.py). Inherited page verification metadata is not the Git admission authority; missing `verified` must not erase a genuine exact-revision admission.
- **Agents cannot manufacture system trust claims.** Proposal editing refuses introduced, changed or removed system-owned generation/verification/attestation claims. [proposals._refuse_forged_claims](../../src/ariadne/proposals.py#L488-L547)
- **Governed numbers do not come from agent-authored SQL.** `get_metric` and `query_metrics` render/plan declared metrics, bind compiled statements and return actual execution rows and SQL. Multi-fact responses also carry lineage/audits and admission provenance. [QueryRuntime](../../src/ariadne/query.py#L403-L460); [query_metrics](../../src/ariadne/query.py#L634-L684); [Execution](../../src/ariadne/execution.py)
- **Answers carry the actual rule text.** Metric responses include the full served metric page and cited Policy bodies, with an explicit `attestation: pending` caveat when applicable. Do not replace those bodies with metadata alone. [ADR-0011](../adr/0011-context-carrying-answers-and-skill.md); [context.metric_context](../../src/ariadne/context.py#L213-L279)
- **Mapping evidence has its own meaningful freshness and authority checks.** Term resolution discloses evidence state; expired mapping evidence cannot retain current confirmed guidance. Measurements and human-confirmed assertions remain separate. This is already implemented, not a new recommendation. [context.evidence_freshness and mapping views](../../src/ariadne/context.py#L1926-L2098); [QueryRuntime.resolve_term](../../src/ariadne/query.py#L840-L880); [ADR-0017](../adr/0017-context-schema-and-identifier-knowledge.md)
- **Schemas, source-linked claims and scoped References already have an owning design.** Do not reopen them or introduce another knowledge registry because the article mentions provenance. [Specification 0010](../specs/2026-10-02-0010-context-layer-schema-and-identifiers.md)

## 3. Recommended next round

### A. Correct freshness interpretation — first priority

`context._freshness_view` only accepts strings parsed by `date.fromisoformat`. Valid offset timestamps therefore return `unknown`, regardless of whether they expired or are in the future. YAML's native datetime values also return unknown and lose the disclosed expiry. The public term-match envelope uses this function for page freshness. [Implementation](../../src/ariadne/context.py#L2101-L2151)

Synthetic probe, importing the current repository source:

```text
2000-01-01T00:00:00Z -> unknown  (expired instant)
2099-01-01T00:00:00Z -> unknown  (future instant)
2000-01-01          -> stale    (legacy date string)
YAML-native UTC datetime -> unknown, stale_after: null
```

**Proposed minimum:** one shared normalization/comparison in Context, accepting supported timestamp forms and explicit YAML date/datetime values, respecting offsets and the exact expiry boundary. Preserve the historical date-only convention; absent, invalid or timezone-ambiguous timestamps remain unknown, not current. Do not rewrite existing artifacts on read or refresh expiry merely because something was queried.

The legacy `_stamp_pages` still emits a blanket date-only 90-day expiry. Any new-generation adjustment should follow the already-approved datetime/evidence rules in specification 0010, without inventing one TTL for both business Policies and live measurements. The Git finalizer deliberately avoids wall-clock restamping. [Stamping](../../src/ariadne/context.py#L686-L729); [Git finalization](../../src/ariadne/context.py#L767-L803); [specification 0010 §§4, 8–9](../specs/2026-10-02-0010-context-layer-schema-and-identifiers.md)

Future regression scenarios: expired/future offset instants, equivalent instants in different offsets, `now == stale_after`, YAML-native timestamps, legacy date compatibility and absent/malformed values. This is a small compatibility correction, not a freshness service.

### B. Make lifecycle and trust visible to consumers — second priority

`search_context` labels physical staged versus served roots with `draft`, but has no structured lifecycle/trust/freshness view. A served deprecated page is returned as `draft: false`; its real status is only in the full content. `metric_context` attaches Policy bodies but does not summarize an expired/deprecated dependency. Raw evidence is present; the gap is deterministic interpretation and explicit disclosure, not hidden content. [search_pages](../../src/ariadne/context.py#L150-L207); [metric_context](../../src/ariadne/context.py#L213-L261)

The synthetic probe returned a deprecated, expired Policy as a normal served search hit and attached it to its metric context. Neither response carried a structured lifecycle warning. A reader must parse the frontmatter itself before treating the rule as current.

**Proposed minimum:** an additive, shared Context view exposing declared status, freshness, relevant generation/verification/source evidence, and dependency warnings on search/term/metric results. Keep actual admission route/revision separate from document-level OKF trust. Preserve full pages, passage pointers, ranking, sources and existing governed/ad-hoc labels.

`governed: true` continues to mean human admission—not fresh, independently numerically checked or suitable for every reporting period. An expired Policy should be visibly qualified, not silently converted into an ad-hoc number. Missing optional metadata should remain unknown, not falsely current and not blanket rejection.

Start with warnings, consistent with the existing non-failing context contract. Whether new work must exclude deprecated definitions, or a particular financial consumer must refuse expired Policies, is a separate owner-approved behavioral choice. Preserve history and do not silently change current search eligibility or query failure semantics. [ADR-0011](../adr/0011-context-carrying-answers-and-skill.md); [specification 0010 §6](../specs/2026-10-02-0010-context-layer-schema-and-identifiers.md)

Future regression scenario: a metric citing an expired/deprecated Policy retains its result and complete caveat bodies while exposing the dependency warning identically through the shared adapters. A Git-admitted page lacking `verified` retains accurate admission provenance without fabricating a document-verification entry.

### C. Clarify attestation terminology now; defer the ABI

Ariadne's generated computation pages cite an independent golden-value test or say `attestation: pending`; they contain an OSI expression fragment and no OKF parameter/executor/receipt contract. [context._write_computations](../../src/ariadne/context.py#L623-L683); [CONTEXT.md](../../CONTEXT.md)

There are three different claims:

1. **Definition admission:** a human reviewed the exact model/context revision.
2. **Execution provenance/fidelity:** this sanctioned definition ran, and the reported value matches its execution result—OKF runtime attestation.
3. **Independent numerical validation:** a separate expected-value source checks the answer—Ariadne's current numerical-attestation convention.

Do not relabel a compiler pass or a stored `attester` path as a successful per-run OKF verdict. Conversely, do not require a golden-value oracle merely to implement execution provenance. They answer different questions.

Ariadne already structurally controls which SQL reaches Execution and returns its rows. That substantially addresses the sanctioned-method concern, but is not a portable OKF receipt or a guarantee that arbitrary conversational prose repeats those rows faithfully. A stored test reference also does not prove that every current run has been independently checked.

**Recommendation:** document this distinction in the relevant vocabulary/consumer guidance through a scoped approved change. Keep existing fields honest. Do not rename computation types or implement general script execution from OKF resources. Specification 0010 explicitly excludes the Google executor/receipt ABI; adding it requires a new approved scope.

If a downstream UI/report actually needs an auditable per-answer verdict, reuse Query/Execution and exact admission provenance. First define the real consumer and its controlled final-value surface, then shape a core-owned execution receipt and deterministic comparison. A hash of an agent-supplied SQL/result is not independent proof; receipt authority and result fidelity must come from the actual executor. No receipt registry, backend replacement or attester-plugin system is justified by this article alone.

## 4. Explicit non-recommendations

- No trust score, popularity-based approval, automated Promotion or weaker source/admission gates.
- No migration away from OKF/OSI/DuckDB, second context store or generic OKF importer.
- No duplicated executable SQL in Markdown; OSI remains authoritative.
- No post-admission modification of reviewed Git bytes to stamp `verified`.
- No claim that a fresh timestamp proves current live-data correctness.
- No schema/mapping feature reimplementation; its existing evidence, confirmation and live-audit boundaries remain intact.

## Verification and handoff

Validation obligation: **existing-check** for this research unit. Compared primary specification/sample passages with current source and accepted contracts. Ran a corrected focused synthetic probe with `uv run --no-sync python -`, `PYTHONPATH=src` and bytecode writes disabled; it exited 0 and used only a disposable temporary directory. The first invocation failed from probe-string quoting before exercising Ariadne and supplies no behavioral evidence. No full test suite, live-data validation, product-code change, dependency change, commit or publication is claimed.

Follow-up acceptance cases above are proposals, not new tests or an executable implementation plan. The owning next-round behavioral choices—especially warnings versus refusals and any runtime-receipt requirement—need approval before implementation. Existing glossary/ADR/spec owners must be reconciled if their scope changes. Planning-contract v1; installed skill provenance unknown. Research disposition: **accept the evidence; ask before behavioral changes**.
