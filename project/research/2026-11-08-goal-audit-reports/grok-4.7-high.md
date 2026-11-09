# Independent audit: shared Lumio workspace goal

Auditor: grok-4.7. Read-only inspection of /home/volker/coding/ariadne. No tests run. Claims below are from files read in this session.

## AREA 1: Data pipeline
Verdict: PARTIAL

What exists. Upload accepts .csv/.json/.parquet/.xlsx only (`intake.py:18-19`, refuse at `51-54`). `prepare_data_source` routes an upload through `_import_upload` or an owner opaque handle through `_operator_binding` (`analytics.py:243-291`). Operator types in the registry include sqlite, duckdb, postgres, delta, iceberg, ducklake (`sources.py:13-25`, `90-100`). Source approval writes an append-only grant keyed by approval digest of endpoint, scope, credential fingerprint, and provenance (`authoring_sources.py:419-421`, `478-510`). `profile_data_source` and `query_data` both call `_grant`, which requires operation status `data_granted`, a stored `approval_digest`, and `approval_state(...).matches` (`analytics.py:178-194`, `470-486`, `511-548`). Query operations are a closed set: `query_metrics`, `query_detail`, `query_records`, `define_metric` (`analytics.py:531-533`). Record queries are capped (default 10, max 1000) and labeled `governed: false` (`query.py:1157-1164`, `1224-1228`). XLSX conversion records `formula_evaluation: false`, `recalculation: false`, `cache_freshness: unknown`, and an explicit limitations list (`spreadsheet_import.py:580-604`).

What is missing or broken. Spreadsheet bytes are opened and turned into a DuckDB artifact during prepare, before any browser approval (`analytics.py:280-291`, `332-336`). The review page then claims "No source schema or data is opened by this review" (`analytics.py:1068-1070`). That sentence is true of the HTML render and false of the prepare step that already interpreted sheets, types, and formula caches. Approval binds the derived digest, not unread bytes. For every source, `profile()` returns `foreign_key_candidates` and `primary_key_candidates` (`profiler.py:426-440`) inside the agent-visible `profile` dict (`analytics.py:502-507`). Only the XLSX branch attaches "Business meanings, units, currencies, and joins are not inferred." Non-xlsx profiles have no such disclaimer in the payload. `query_data` returns the runtime answer unchanged, including compiled `sql` (`analytics.py:549-560`). `define_metric` is exposed on the same tool, so the agent can author a calculation, not only call a governed metric.

## AREA 2: Knowledge
Verdict: PARTIAL

What exists. `prepare_enrichment` selects pages from the admitted published pointer and refuses a stale `expected_version` (`enrichment.py:101`, `164-174`). It does not publish. Knowledge approval calls `publication.publish` -> `publish_revision` and only then marks the task published (`review.py:527-551`, `publication.py:58-72`). Analytics approval calls `admission.admit_revision` and requires `activated` (`analytics.py:1000-1024`, `publication.py:97-118`). Agent search and read open `PublishedFilesystemLocation` and refuse an invalid snapshot (`app.py:306-314`, `327-360`). The lexical ranker builds `snippet` from the matched field via `_search_excerpt` (`page_search.py:55-79`, `132-152`).

What is missing or broken. `search_knowledge` returns `citation: {title, path, version}` plus `passage: result.snippet` (`app.py:354-359`). The excerpt is at most 260 characters around the first token hit, and a title/alias hit can be the "passage." `location.retrieve()` exists and documents citation-ready evidence (`location.py:281-300`); the workspace tool does not call it. Line anchors exist only on the human review page (`review.py:571-576`). So search does not return the cited passage actually used; it returns a truncated ranker excerpt and a page pointer. The agent must call `read_knowledge` and hope. Two publish stacks (wiki `publish_revision` and Core `admit_revision`) both have to succeed for the two contribution kinds; a failure in either leaves a task that `reconcile_task` may only recover if a receipt already exists (`review.py:428-509`).

## AREA 3: Agent consumption
Verdict: PARTIAL

What exists. The Pi client blocks workspace tool calls and aborts provider requests when the model is not in `LUMIO_WORKSPACE_ALLOWED_MODELS`, and it keeps a disclosure entry across compaction (`index.ts:87-136`). `/workspace` text says not to infer dates, units, or joins; XLSX uses stored caches without recalculation; `query_data` rechecks the source-set grant (`index.ts:237-252`). The skill forbids raw SQL, says record queries and `define-metric` are `governed: false`, and states the workspace exception: the agent prepares, a separate browser review decides (`SKILL.md:8-22`, `100-135`, `631-659`). The MCP operation enum rejects a raw SQL string (`analytics.py:531-533`).

What is missing or broken. Pi guidance never says "no raw SQL" or "no self-approval." Exact-byte upload is local-token only (`index.ts:146-148`); Entra mode cannot upload. The skill omits the single-person self-approval carve-out in `review.py:395-403`. `query_data` still hands the model compiled SQL. The skill tells the agent not to invent from it; the tool result does not strip it.

## AREA 4: Collaboration
Verdict: PARTIAL

What exists. `decide` holds `mutation_lock` on activation, destination, registry, and artifacts, rechecks `review`, and refuses a non-`pending_review` task (`review.py:377-388`, `171-180`). Review actions are one-shot, actor-bound, and binding-matched (`state.py:543-594`). A second serialized approve fails the status check or `finish_review_task`'s conditional update (`state.py:509-540`). Retry keys reject a changed input (`state.py:366-392`). `get_task` and `reconcile_task` cover disconnect. Membership `revoke` and credential `revoked_at` are checked on the next call (`state.py:311-339`, `356-364`, `686-687`; `app.py:484`). Restore clears outstanding review actions (`operations.py:186-238`).

What is missing or broken. Self-approval is allowed when the workspace has exactly one member (`review.py:395-403`, `state.py:622-628`). That contradicts the stated rule. A data grant is an operation status, not a membership row. Revoking `read` stops `query_data`; re-granting `read` restores the old `data_granted` row with no new browser decision (`analytics.py:184-194`). There is no revoke-data-grant path. Backup copies `state.sqlite3` with `shutil.copy2` under activation locks and says the service must already be stopped (`operations.py:110-155`). `WorkspaceState._connect` does not take that lock (`state.py:182-183`) and sets no WAL/backup API. A live copy can tear. The restore path is real only if the copy was consistent.

## AREA 5: Simplicity
Verdict: PARTIAL

The workspace modules that implement the goal are already large: `analytics.py` 1130 lines, `review.py` 1016, `app.py` 928, `contributions.py` 797. They sit on libraries far past this goal: `lumio_wiki/cli.py` 10629, `knowledge_base.py` 5646, `git_authoring.py` 4148, `ariadne/context.py` 4279, `authoring.py` 3932, `planner.py` 3030. One approve click depends on two publication stacks, a private profile, Git worktrees, and a 683-line lock module whose contract comment is longer than the lock (`mutation.py:1-62`). The agent search path does not use the retrieval/citation stack it documents. `define_metric` is a second calculation path beside governed metrics. Entra and local-token are both live. None of that is required to upload a CSV, approve a digest, and run a governed query. The gates themselves are not decorative; the surrounding machine is.

## MISSING
- Approval before spreadsheet interpretation. XLSX is converted in prepare; the review page denies that data was opened (`analytics.py:280-291`, `1068-1070`).
- A payload-level "not a join" label on profiler `foreign_key_candidates` for non-xlsx sources (`profiler.py:429-440`, `analytics.py:502-507`).
- Agent search that returns the passage actually used, with a stable anchor. Current result is a 260-char excerpt plus title/path (`app.py:354-359`, `page_search.py:55-79`). `retrieve()` is unused by the workspace tool.
- Pi text for "no raw SQL" and "no self-approval" (`index.ts:237-252`). Skill omits the solo self-approval exception (`SKILL.md:649-659` vs `review.py:395-403`).
- Independent revocation of a data grant. Re-granting `read` revives `data_granted` (`analytics.py:184-194`).
- A backup that is safe while the server is up. Current path is a stopped-service file copy (`operations.py:110-115`, `130`).

## OVER-COMPLICATED
- Dual publishers for one product action: `publish_revision` and `admit_revision` (`publication.py:58-118`).
- `define_metric` on the workspace query tool next to governed metrics (`analytics.py:552-553`).
- FK-candidate inference in the profiler while the skill says observations never authorize joins (`profiler.py:415-418`, `SKILL.md:631-635`).
- `mutation.py` lock essay and temp-dir flock for a single-process service that backup docs say must be stopped.
- Unused-by-the-tool retrieval/Lance path beside the lexical search the agent actually calls (`location.py:281-300` vs `app.py:347-360`).
- Library mass the goal does not need: `cli.py` 10629, `knowledge_base.py` 5646, `context.py` 4279, `authoring.py` 3932, `planner.py` 3030.

## OVERALL
Verdict: PARTIAL
The upload, digest-bound approval, grant check, governed query, and browser publish path are real code, not stubs. A caller cannot profile or query until `data_granted` matches the current source identity, and a second reviewer cannot replay one action digest. The goal is still not met. Spreadsheets are interpreted before approval. Search does not return the cited passage used. Solo self-approval is implemented. Data grants are not revocable on their own. Backup is a stopped-service copy. The Pi client and skill state most limits and omit two that the server violates or returns. The working path is buried under a library an order of magnitude larger than the product action.
