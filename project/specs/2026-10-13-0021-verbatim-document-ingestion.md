# Specification: Verbatim document ingestion

**Accepted scoped Git-only amendment (2026-10-16):** [Specification 0027, written revision 1](2026-10-16-0027-core-git-only-authoring.md) captures the owner-approved bounded Core direction; the owner approved the complete written revision and these scoped amendments with “Schriftliche Fassung freigeben (Recommended)”. Existing converters, exact converted-text/consent/bounds/no-overwrite semantics remain; candidate Git revisions replace staging identity/idempotence, and originals remain external private operator inputs. Unaffected original approval remains; no implementation or shared #76 contract is approved by this notice.

| | |
| :--- | :--- |
| **Status** | **Approved, revision 1** |
| **Approved design direction** | Owner, Pi conversation 2026-10-13: prioritize `--verbatim`; accept the bounded staging-only design and select all existing document formats, not only Markdown/Text. The owner subsequently requested written `shape-design` capture before implementation. |
| **Approval** | Owner, this Pi conversation 2026-10-13: “approved.” in response to the written specifications 0021 and 0022 and ADR-0022. Approval covers the complete revision-1 behavior and proceeding to implementation planning; it does not approve unseen plans, source access, target integration or publication. |
| **Scope** | An optional no-LLM mode of standalone document ingestion, preserving converted document text in one draft Reference per document; staging-local idempotence and never-overwriting revisions. |
| **Existing contracts** | [ADR-0009](../adr/0009-standalone-proposal-first-ingestion.md), [MVP acceptance examples 19–20](./mvp-vertical-slice.md), [Evidence Reconciliation 0004](./2026-09-23-0004-evidence-reconciliation.md), [Git authoring 0009](./2026-10-02-0009-modular-core-git-authoring.md), [Context schema 0010](./2026-10-02-0010-context-layer-schema-and-identifiers.md), [Context browsing 0015](2026-10-12-0015-context-page-browsing.md), [vocabulary](../../CONTEXT.md) |
| **Evidence** | [ktx comparison and owner follow-up](../research/2026-10-13-ktx-gaps-after-usability.md); current [`ingest.py`](../../src/ariadne/ingest.py) at `a8d24b18d16854058e6b2b97bd1801cb0687ffbd` |
| **Contract** | planning-contract v1; installed skill provenance unknown |

## 1. Purpose and non-goals

Retain source documents without model summarization, paraphrasing or classification. This supports source-linked project knowledge without replacing the existing distilled-ingestion path. An unchanged document is evidence, not automatically an admitted Policy or a governed calculation.

In scope: the existing standalone CLI and Python seam, existing format conversion, mechanical Reference metadata, all existing input/staging gates, one complete converted document per draft, same-source retries and non-destructive new versions.

Non-goals: a Wiki/Lumio connector, new converters or dependencies, embeddings, document splitting, automatic Policy/Table classification, extracted structured terminology declarations, metrics/OSI generation, automatic reconciliation or admission, changes to Answer Examples, and an ingest MCP tool. This does not migrate standalone staging into Git-backed authoring.

## 2. Interface and data flow

```text
ariadne-ingest DOC... --verbatim [--staging DIR]

ingest(docs, *, staging_dir="staging", complete=None, verbatim=False)
    -> (newly_staged_paths, errors)
```

`--verbatim` and the Python keyword are opt-in. Calls without them retain their existing LLM-distillation behavior and result shape. In Verbatim mode no completion callback or configured LLM endpoint is invoked, and no LLM configuration is required.

The pipeline is:

```text
explicit document -> existing converter -> mechanical Reference wrapper
                  -> existing content/page/path gates -> exclusive staging write
```

Every successfully converted non-empty document produces at most one new page under `staging/context_layer/references/`. Its Ariadne frontmatter carries `type: reference`, `status: draft`, a deterministic filename-derived title/description, `ingest` and `verbatim` tags, the existing document source binding (content digest, resolved source location and filename), and `generated.by: ariadne-ingest:verbatim` with a generation time. Metadata contains no model claim, verification, admission, grain or calculation authority.

The source document's own frontmatter, headings and content remain literal body text. They cannot supply Ariadne lifecycle fields, sources, structured `ariadne` declarations or approval state. The wrapper is a new Ariadne record, not a blind import of an existing OKF page's authority.

`--verbatim --reconcile` is explicitly refused before conversion, model calls or staging. The existing LLM-supported reconciliation operation is unchanged; a future combination needs its own design. Existing `--db` compatibility remains unchanged and adds no database access to this mode.

## 3. What “verbatim” preserves

Verbatim means **the exact text returned by the existing reader/converter**, not byte-identical preservation of an original binary document or its visual layout. It adds no trimming, paraphrasing, heading changes or terminal-newline normalization to that text when constructing the page body. Ariadne's generated frontmatter and its body separator are additional, clearly distinguishable metadata.

- `.md` and `.txt` use the existing native reader. Original textual frontmatter is preserved as content, not adopted as Ariadne metadata. Existing reader decoding/newline behavior is not changed.
- PDF, Office, HTML and other currently supported formats use the current converter dispatch and optional `documents` extra. Their preserved text is the converter's Markdown output; conversion can already lose layout or OCR fidelity.
- Whitespace-only converted output is refused as empty, rather than producing an invalid Reference. Missing converters and unsupported formats retain their actionable errors.

Verbatim does not redact or silently alter a document to make it acceptable. If the preserved text or wrapper fails the existing credential or page contract, that document is refused and stages nothing.

## 4. Identity, retries and failure behavior

Within the selected staging root, a repeated Verbatim intake of the same resolved source location, unchanged input content and unchanged converted text is a successful no-op when its unchanged Verbatim draft is still present. Generation timestamps do not turn that retry into a new version. The Python result lists only newly staged paths; a no-op therefore adds none. The CLI must report the unchanged/no-op case honestly, not claim another page was staged or that the source contained no useful content.

Changed source content, changed converted text, or a different resolved source location creates a separately identified draft. Existing source documents, staged pages and served pages are never overwritten. Human edits to an earlier draft are retained; a differing draft cannot be overwritten or misreported as byte-identical retry output. Names follow the existing safe-slug/exclusive-write collision discipline.

This is staging-local deduplication, not a permanent intake ledger. It does not inspect served roots, promise cross-checkout deduplication, or prevent a new draft after an earlier one has left staging through human Promotion.

The existing staging-root and symlink refusals apply before either a write or a deduplication read: no read through an escaping staging link and no write through a symlink into served state. Reuse existing per-type validation, credential scanning and atomic exclusive writes rather than a second ingestion framework.

Failures name the document and the violated contract or missing prerequisite. Credential errors name the pattern class, never the matched secret. A failed document produces no new page; independently successful documents in the same batch may remain staged, as today. No batch transaction or global rollback is promised.

## 5. Authority, discovery and compatibility

Only the normal human Promotion path can move this standalone Reference into served state. Git-backed reuse, if desired, is an explicit proposal edit under its existing source/document and admission rules, not a new ingestion shortcut.

Drafts are immediately discoverable through the existing staged Context Layer search/list/read behavior, correctly labeled as drafts. No new search lane, result shape or ranking authority is added. After Promotion the normal served Reference contract applies; neither intake nor technical validation independently attests business meaning.

The public guidance must distinguish preservation from extraction: use Verbatim for retaining original converted wording; use ordinary ingestion to propose classified/distilled pages. Describe optional converter requirements and the unsupported reconciliation combination. No automatic change to installed user skills is part of the feature implementation.

## 6. Observable acceptance criteria

1. A Markdown fixture containing textual frontmatter, leading/trailing whitespace, a code block and no final newline becomes one draft Reference whose extracted document body equals the native reader's text exactly. Its own `status: stable` text does not change the outer `status: draft`. No completion callback is called.
2. A supported non-native document uses its existing converter and retains that converter's text exactly, without an LLM call or new dependency. A missing converter gives the existing installation hint and stages nothing for that document.
3. Repeating the same source/content in the same staging root creates no extra file and does not change the existing draft's bytes or generation time. Changed content creates a new draft and leaves the previous one intact. A distinct source location is not silently conflated with it.
4. Unsupported format, empty output, a credential-bearing body/wrapper or a symlinked staging destination refuses that document without new files, secret disclosure, served mutation or bookkeeping writes. A deduplication attempt cannot read through the forbidden symlink either.
5. `--verbatim --reconcile` fails before conversion, staging or any model call. The equivalent ordinary ingestion/reconciliation checks remain unchanged.
6. Search/list/read can find the draft with the existing draft label and original body. No Policy, metric, verification or served page is created by the intake itself.
7. CLI and Python retain ordinary ingestion compatibility. The no-op is success and is reported as unchanged; partial-batch failure retains existing exit/error behavior.

Validation obligations: `new-test` for exact preservation/no model, retries and the new mode's reachable gate cases at the existing public ingestion seam; `existing-check` for ordinary ingestion, reconciliation, Promotion and staged discovery. Expected body/provenance values come from the input fixture and these criteria, not generated output. Real-world agent behavior remains the owner's manual check; no recorded-session suite is added.

## 7. Capture checkpoint and handoff

- **Vocabulary:** `Verbatim Ingestion` is captured in [CONTEXT.md](../../CONTEXT.md); Reference, Staging and Promotion retain their meanings.
- **Decisions:** this optional mode preserves ADR-0009's standalone proposal-first architecture. No new ADR is warranted for a reversible mode flag; ADR-0009 and the MVP retain the normal LLM default and point to this scoped extension.
- **Behavior:** the owner approved this complete written revision-1 interface, preservation, retry, gate and acceptance contract with “approved.” in this Pi conversation on 2026-10-13. Execution decomposition belongs to [plan 0021](../plans/2026-10-13-0021-verbatim-document-ingestion.md).
- **Uncertainty:** no material direction choice remains open. Converter fidelity remains an explicit limit, not a promised guarantee. Plan approval/readiness precedes writer dispatch; actual source access, integration and publication retain separate authority.
