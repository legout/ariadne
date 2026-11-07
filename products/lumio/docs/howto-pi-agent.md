# How-to: drive the shared workspace from a Pi coding agent

This guide stitches the existing workspace documentation into two concrete,
walkable workflows for a **Pi agent**: contributing documents, and requesting
plus querying structured data. It adds no new behavior — configuration,
authority boundaries, and honest limits live in the canonical guides:

- Operator setup (service, users, credentials, HTTPS):
  [howto-shared-workspace.md](howto-shared-workspace.md)
- Operations (launch, backup, restore):
  [howto-workspace-operations.md](howto-workspace-operations.md)
- Data sources and queries: the Ariadne-side
  [data how-to](../../ariadne/docs/how-to/shared-workspace-data.md)
- The verified end-to-end journey with expected values:
  [shared-workspace-journey](../examples/shared-workspace-journey/README.md)
- Extension internals: [clients/pi-workspace](../clients/pi-workspace/README.md)

> **Accepted interim limitation:** Pi's shell inherits its process
> environment, so the API token can surface in tool output until host
> isolation is qualified — synthetic credentials/data only, and browser
> credentials never enter Pi. Live legs (two humans, private HTTPS,
> installed Pi) remain open; see the journey README for status.

## 1. Connect Pi to the workspace

The operator installs
[`products/lumio/clients/pi-workspace`](../clients/pi-workspace/) as a
trusted Pi extension and delivers the agent user's API token through the
operator-controlled environment (never chat or tracked files):

```sh
export LUMIO_WORKSPACE_AUTH_MODE='local-token'
export LUMIO_WORKSPACE_URL='https://WORKSPACE_HOST'
export LUMIO_WORKSPACE_API_TOKEN='USER_API_TOKEN'
export LUMIO_WORKSPACE_ALLOWED_MODELS='APPROVED_PROVIDER/APPROVED_MODEL'
```

After reloading Pi, run `/workspace` (connection guidance and model
disclosure status) and `/mcp` (inspect `lumio-workspace`). Reads use
`workspace_status`, `read_knowledge`, and `search_knowledge`. Reads are
blocked for any provider/model outside the owner's allowlist — including
after a model switch — and history carrying workspace results never travels
to a nonallowed model.

## 2. Contribute a document (text or binary)

Use the synthetic files from the [sample corpus](../examples/sample-corpus/) to walk
this first (`operations-notes.md`, `supplier-brief.pdf`,
`installation-note.docx`).

1. **Upload exact original bytes** with a stable retry key from the first
   attempt (`.txt`/`.md`/`.markdown`/`.pdf`/`.docx`, up to 25 MiB):

   ```text
   /workspace-upload ops-notes-v1 operations-notes.md retry=ops-notes-v1
   ```

   The result is an **`upload_id`** — not a task ID. Keep the key, source
   ID, filename and exact bytes; an interrupted upload is recovered by
   repeating the same invocation, and a lost key or changed bytes cannot be
   recovered.

2. **Inspect the retained conversion** with `read_source_material`: it
   returns the actual processor (LiteParse for PDF, AnyDoc for DOCX) and any
   `incomplete` truncation signal. Never describe truncated output as
   complete.

3. **Prepare the contribution** with `prepare_contribution`, using the
   recovered `upload_id`, explicit source intents, and a **separate stable
   preparation `retry_key`**; retain the returned **`task_id`** and poll it
   with the actor-scoped `get_task`.

4. **Point the human at the browser review.** Candidate approval is a
   separately authenticated human action in the browser; no MCP tool, token,
   or agent performs it. Changed candidates require a fresh review.

## 3. Request data, profile it, review the change, then query it

With analytics enabled by the owner, use the structured corpus files
(`orders.csv`, `orders.json`, `orders.parquet`, `catalog.xlsx` from the
[sample corpus](../examples/sample-corpus/)).

1. **Upload the structured bytes** exactly as above (`/workspace-upload`),
   retaining the returned **`upload_id`**.

2. **Request the source without opening it**: `prepare_data_source` with a
   stable `retry_key`, the configured `project` and `source` handles, the
   `table`, the known `business_questions`, and — for a structured upload —
   the returned `upload_id`. CSV, JSON, and Parquet use their native
   handlers and take no `sheets`; only XLSX additionally takes an explicit
   `sheets` list (try `["pricing"]` from the sample corpus; selecting the
   cache-less `draft_totals` sheet deliberately demonstrates the documented
   `missing_formula_cache` refusal). The service stages a native source
   proposal and returns a `task_id` and `review_url`.

3. **Two browser reviews follow** (human, never in Pi): the **Source
   Approval** binding the complete resolved source identity, and the
   **data authorization** granting the requester that source set. Ask the
   reviewer to open the `review_url` in their browser session.

4. **Profile after both grants**: `profile_data_source` with the source
   `task_id` returns measured schema, row, and type facts. Facts never
   infer business rules or authorize joins — and neither the approvals nor
   the profile admit anything.

5. **Review the combined change**: `prepare_contribution` with the granted
   `source_task_id`, the exact uploaded document sources, and the authored
   pages and native edits. Its first browser review binds the complete
   candidate (knowledge, Policy text, native changes, conversion facts);
   the second performs the **overall admission** that activates the
   governed revision.

6. **Query the admitted revision**: `query_data` with `get_metric`/
   `query_metrics` (governed), `query_detail`, `query_records`, or an
   explicitly ungoverned one-shot `define_metric`. Its prerequisite is the
   admitted revision from step 5 — source approval, data authorization and
   profiling alone make nothing queryable. Answers carry the governance
   label, mandatory context, citations, and the pinned commit.

The exact contracts live in the
[data how-to](../../ariadne/docs/how-to/shared-workspace-data.md).

## 4. What Pi must never do

- Never issue, capture, or receive a human's browser credential or cookie.
- Never replay or predict browser approval; stale consent cannot activate.
- Never widen a source request, sheet selection, or grant on its own.
- Never present profile facts, cached spreadsheet values (freshness is
  unknown), or ad-hoc results as governed or value-attested.
