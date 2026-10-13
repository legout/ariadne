# Specification: Answer Example SQL provenance

| | |
| :--- | :--- |
| **Status** | **Approved, revision 2** |
| **Approval** | Owner, this Pi conversation 2026-10-13: “approved” in response to the complete written specification revision 1. Revision 1 approval covers its exact save, record, retrieval, review, compatibility, limits and acceptance contract and proceeding to implementation planning. Revision 2 additionally captures the owner's request in the continued conversation to amend #68 based on the agreed active-feedback rule below. Neither approval authorizes implementation, worker dispatch, integration or publication. |
| **Design approval** | Owner, this Pi conversation 2026-10-13: selected SQL retention on every explicitly confirmed future save and SQL retrieval only on request; then answered “Ja passt” to the complete in-chat design covering save, retrieval, review, compatibility, limits, non-goals and four acceptance scenarios. |
| **Scope** | Preserve submitted `result.sql` as non-executable historical provenance in existing Answer Examples; expose it through opt-in example search; guide the Ariadne agent to actively request feedback and explicit saving when no suitable reviewed Example exists. |
| **Existing contracts** | [Answer Examples 0007 revision 1](./2026-09-29-0007-answer-examples.md), [ADR-0015](../adr/0015-separate-answer-example-store.md), [vocabulary](../../CONTEXT.md) |
| **Evidence** | [ktx comparison and follow-up](../research/2026-10-13-ktx-gaps-after-usability.md); current [`answer_examples.py`](../../src/ariadne/answer_examples.py), [`example_review.py`](../../src/ariadne/example_review.py), [`query.py`](../../src/ariadne/query.py) and [`serve.py`](../../src/ariadne/serve.py) at Ariadne `a8d24b18d16854058e6b2b97bd1801cb0687ffbd`. No new behavior has been implemented or exercised. |
| **Contract** | planning-contract v1; installed skill provenance unknown. This document captures the approved bounded design, not execution, integration, publication, ticket creation or installed-skill update authority. |

## 1. Purpose and non-goals

Extend the existing Example-learning path, not create another learning system. The recorded question, interpretation and structured Ariadne method remain the reusable reference; the saved answer and SQL remain historical evidence. Current answers still require current scope/dependency checks and fresh execution through Ariadne's existing gates.

This scoped extension makes SQL retention mandatory for future successful saves and defines opt-in retrieval. All other behavior in specification 0007 revision 1 remains binding, including separate staging/served stores, explicit confirmation and attestation, operator-only review, dependency staleness, independent method checking, unique non-overwriting submissions and truthful governance labels.

Non-goals: raw-SQL execution or replay, automatic comparison against newly compiled SQL, SQL-template learning, external SQL-history import, silent collection, model training, embeddings/LanceDB, new query operations, new storage services or dependencies, a separate `.sql` sidecar, or retroactive modification of old Examples. Supported recorded methods remain `get_metric` and `define_metric`.

## 2. Save and record contract

The existing `save-example` / `save_example(submission)` input remains the observed result envelope plus the existing Example fields. No SQL-storage switch or separately supplied SQL provenance is added. Before saving, the agent presents the complete bounded submission, now explicitly including its SQL text, for the user's confirmation and attestation. A successful query alone is still not permission to save.

Every successful new save derives the following frontmatter field from `submission.result.sql` in the same OKF Example file:

```yaml
sql_provenance:
  source: submitted_result.sql
  text: "SELECT region, COUNT(*) FROM orders GROUP BY region"
```

`source` is the fixed descriptor `submitted_result.sql`, not a verified execution origin. `text` is the exact submitted SQL string: no trimming, formatting, newline normalization, parameter substitution, masking or truncation. The illustrative SELECT above is data, never a method argument. Valid text is a non-whitespace string. YAML encoding may escape characters, but parsing must recover the original string exactly. An independently supplied top-level `sql_provenance` is a reserved-field error; the system derives it only from the validated result envelope.

The existing historical answer excerpt and full structured-result digest remain unchanged. No additional SQL hash, signature or authenticated execution receipt is introduced. A local submission can supply its own result envelope; neither the existing digest nor SQL retention proves a prior execution, correspondence between SQL and the structured method, historical numeric correctness or business meaning. Technical review retains its existing responsibility.

The answer excerpt stays limited to 8 KiB UTF-8. SQL shares the existing 64-KiB encoded whole-record limit with every other field; it has no separate quota. Invalid or oversized input fails before any Example or bookkeeping write, leaving existing records untouched. Never silently drop or shorten SQL to fit. The reviewed record must also satisfy the existing overall bound after review metadata is added.

Credentials and inappropriate sensitive content must not be submitted or retained, as required by specification 0007. The pre-save confirmation includes SQL literals and references so the user can assess retention. Automatic redaction or a new general sensitive-data classifier is not part of this feature; do not rewrite SQL or fabricate a different observed result to make a submission acceptable.

## 3. Opt-in retrieval

```text
ariadne search-examples QUERY [--limit N] [--include-history] [--include-sql]

search_examples(query, limit=10, include_history=False, include_sql=False)
```

The local CLI and optional MCP use the same transport-neutral behavior. The default is `include_sql=False`: current search ranking, record selection and JSON response shape remain unchanged; no SQL text or new SQL availability field is added. SQL is not searched or used to rank Examples.

With `include_sql=True`, each returned hit adds `provenance.sql`, containing the stored `sql_provenance` mapping. It remains explicitly historical submitted-result evidence alongside the hit's existing draft/stable, stale and review information. Missing SQL provenance yields `provenance.sql: null`, documented as “not recorded”; neither a digest nor a fresh query is used to invent it.

A present but malformed provenance field is not treated as missing. If a selected hit has an invalid mapping, source descriptor or text, opt-in retrieval fails with an identifiable validation error through the existing error envelope, without returning that SQL as usable provenance. Default search retains its existing behavior. SQL retrieval executes no saved statement and does not change the structured method, source approvals or compile gate.

History remains separately opt-in: `--include-sql` alone does not expose stale, superseded or rejected Examples that normal search excludes. When both options are selected, historical hits retain their existing truthful labels.

## 4. Review and compatibility

For a staged record with SQL provenance, operator approval validates the mapping, fixed source descriptor and non-whitespace text as well as the existing record. Malformed SQL provenance refuses approval before any stable-record write. The existing review digest binds the exact staged bytes, including the SQL field. Review retains the SQL string unchanged while adding ordinary review metadata; it does not execute SQL or independently attest historical values.

Existing Examples without the field remain valid for search and their existing review path. They are not rewritten, downgraded or excluded solely because SQL is unavailable. An absent field records unavailable provenance, not an authenticated age/version claim. No backfill, migration job or format-version framework is required. Existing revisions, supersession, staleness, root/path protections and separate managed citation/example-store roots remain unchanged.

Public guidance and the packaged Ariadne skill must explain confirmation of the SQL-bearing record, opt-in retrieval, legacy absence and non-executable reuse. Candidate behavior must not be misrepresented as already published in Ariadne 0.2.0. Refreshing installed user skills, release and publication require separate authority.

## 4a. Active feedback in the Ariadne skill

This is agent guidance in the bundled Ariadne skill, not a runtime prompt, correctness classifier or automatic save. For answers produced through the supported `get_metric` and `define_metric` methods, look up Examples and check candidates against the current question. A suitable reviewed Example must be stable, non-stale, eligible for normal reuse and compatible in interpretation, method, parameters, grain and current Policies; lexical similarity alone is insufficient. Its method still requires current validation and fresh execution.

If a suitable reviewed Example is used, do not add an unsolicited save question. If none is found, including when only drafts or unsuitable/stale Examples exist, ask once after the completed answer:

> Passt die Interpretation und ist die Antwort für dich fachlich stimmig? Soll ich das gezeigte Beispiel speichern?

Present the bounded Example submission, including SQL, before confirmation. Keep three choices distinguishable: correct/useful and save; correct/useful without saving; or correct the interpretation/answer. Only explicit agreement to the shown submission and the existing business-meaning attestation permits saving. Agreement to correctness alone, ambiguous assent, silence or a correction stores nothing. After a correction, resolve it before presenting a revised submission for explicit confirmation; do not repeatedly solicit a save for the same answer. An independent explicit save request remains possible even when a reviewed Example was used. A confirmed save creates an unreviewed draft, never an automatic approval.

User feedback is a self-declared business-meaning assessment, not independent numeric validation. “The example” means the displayed bounded record, not the conversation transcript. This guidance does not add a configuration switch or change CLI/MCP save validation.

Canonical storage remains the separate OKF `answer_examples` store defined in ADR-0015, not `context_layer/`. A future LanceDB index would be derived and rebuildable from those records, preserving identity, provenance, review and staleness labels; similarity would confer no authority. Building that index remains outside this specification and #68.

## 5. Observable acceptance criteria

1. **Exact save and retrieval:** a confirmed submission with a known SQL literal containing leading/trailing whitespace, multiple lines and no final newline stores that exact string in the same staged OKF Example. Local CLI and MCP opt-in search return identical SQL provenance with the normal draft label. The existing method, result digest and answer excerpt retain their meanings; saving and searching execute no SQL. A separately supplied provenance field cannot override the result-derived text.
2. **Default and legacy compatibility:** ordinary search retains its previous shape/ranking and returns no SQL. An independently supplied legacy Example without SQL remains searchable and reviewable; opt-in search returns `provenance.sql: null`. History selection stays controlled by `include_history`, not `include_sql`, and no old record is mutated or backfilled.
3. **Review preservation and refusal:** approval preserves a valid stored SQL string and ordinary review evidence; changing the staged record after its review digest was taken remains refused. A present malformed provenance mapping/text/source refuses SQL retrieval or approval as applicable and never becomes a silently missing or valid SQL field. Legacy absence alone is not a review failure.
4. **Bounded all-or-nothing save:** an otherwise valid submission whose SQL makes the encoded record exceed 64 KiB is refused before page/index/log writes. No SQL is truncated or omitted, and existing draft/served files remain unchanged. The existing 8-KiB answer-excerpt, invalid-input and path/root gates still apply.

5. **Active, consent-bound feedback:** a manual agent check covers no matching Example, a draft-only match and a compatible reviewed non-stale match. The first two trigger one feedback/save question after a completed supported answer; the reviewed match is freshly executed without an unsolicited save question. Correct/useful without saving, ambiguous assent and correction cause no save; explicit confirmation of the shown record creates a draft. An explicit save request remains possible in the reviewed-match case. No result is labeled independently verified on the basis of user feedback alone.

Validation obligations: manual owner check for AC5 and focused written-skill inspection (no recorded-agent-trace suite or new runtime prompt tests); `new-test` for exact SQL preservation, explicit CLI/MCP retrieval and the reachable malformed/oversized provenance cases; `existing-check` for default search, legacy review, result limits, staleness, supersession and root guards. Expectations come from independent input literals and this contract, not implementation output. Real-agent reuse remains a manual owner check; no recorded-agent-trace suite is added.

## 6. Capture checkpoint and handoff

- **Vocabulary:** `SQL Provenance` is captured in [CONTEXT.md](../../CONTEXT.md). Answer Example and Staging retain their meanings, as do the existing review/governance boundaries; SQL is not a new query operation or Policy.
- **Decisions:** no new ADR is warranted. Keeping provenance in the existing Example page preserves ADR-0015; the opt-in field/flag is a bounded, reversible interface extension, not a new storage or execution architecture.
- **Behavior:** the owner approved the complete in-chat bounded design with “Ja passt” and subsequently this complete written revision 1 with “approved” on 2026-10-13. Revision 2 captures the agreed skill feedback rule through the owner's subsequent request to update #68 accordingly. Its exact field/interface, consent and acceptance contract is ready for implementation planning; #68 owns execution decomposition.
- **Uncertainty:** no material product-direction choice remains open. This is an unauthenticated local provenance record, not execution attestation or a comprehensive sensitive-data classifier. Implementation planning/readiness and execution authority still precede any writer dispatch. Specs 0021/0022 and tickets #66/#67 remain separate and unchanged.
