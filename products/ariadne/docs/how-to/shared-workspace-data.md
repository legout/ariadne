# How to request and query data through a shared workspace

Use this guide when an owner has explicitly enabled the optional Lumio Workspace analytics adapter. It covers the D1 SQLite journey: request a source, approve its exact identity, profile it, review the combined knowledge/calculation change, and query the admitted revision. The ordinary [Git-backed authoring workflow](git-authoring.md) remains the default for local projects.

The base workspace service does not require Ariadne Core. Analytics requires the `lumio-workspace[analytics]` extra and a compatible same-candidate Core installation. A same-version older published Core may not provide the required contribution/admission APIs; version text alone is not compatibility evidence.

## 1. Configure the owner-managed binding

Set the existing authoring and private-profile settings, then add:

```sh
export LUMIO_WORKSPACE_ANALYTICS_PROJECT_ID='retail'
export LUMIO_WORKSPACE_ANALYTICS_PROJECT_PATH='/owner/private/retail-project'
export LUMIO_WORKSPACE_ANALYTICS_SOURCE_BINDINGS='/owner/private/source-bindings.json'
```

These paths stay in the operator environment. Pi callers use only the opaque project handle, source handle, and task IDs. The operator-controlled JSON binding maps each source handle to native declarations, for example:

```json
{
  "orders_sqlite": [
    {"name": "orders_sqlite", "type": "sqlite", "path": "data/orders.sqlite"}
  ]
}
```

Secret environment or file references, when applicable to a native source profile, remain in this operator binding. Never place credentials, server paths, DSNs, approval records, or private profile contents in prompts, tracked source, tool arguments, or review URLs. The native DuckDB/SQLite backing is trusted operator infrastructure, not a sandbox for arbitrary caller SQL.

## 2. Request the source without opening it

Call `prepare_data_source` with a stable `retry_key`, the configured `project` and `source` handles, a `table`, and the known `business_questions`. The service stages a native source proposal in its server-owned worktree and returns a `task_id` and `review_url`.

This preparation creates an inert declaration. It does not open the source, return schema, or make the project query-ready. Repeating the same key with different identified input conflicts rather than replacing the original request.

Two distinct browser reviews follow:

1. **Source Approval** binds the complete resolved native source identity, including its effective non-secret storage binding.
2. **Data authorization** grants the requester that same complete source set. Workspace membership, an API bearer token, or Source Approval alone is not this grant.

The browser GET only displays the exact operation. A separately authenticated reviewer must submit the one-use action. Changed endpoints, declarations, or source scope require a fresh matching review; an unchanged exact grant is reused without being widened.

## 3. Profile only after both grants

Call `profile_data_source` with the source `task_id`. The adapter verifies the current native Source Approval and the caller's current data authorization before invoking native profiling.

The result contains measured schema, row, and type facts for the approved source set. These facts do not infer a business rule, authorize a join, or define a metric. If either approval is absent or stale, the refusal names the required owner/reviewer action instead of returning plausible profile data.

## 4. Review knowledge and calculation together

Use `prepare_contribution` with the granted `source_task_id`, exact uploaded document `sources` and intents, authored `pages`, and native `core_edits`. Keep a separate stable preparation `retry_key` and the complete request for recovery.

The first browser review binds the complete candidate, including Policy text, knowledge changes, unknowns, native model/filter/unit/date/mapping changes, and conversion facts. Approval commits and validates exactly that reviewed candidate; validation's returned evidence-bearing revision becomes the publication candidate.

The second browser review binds the overall native release and performs one overall admission. Knowledge-only approval cannot substitute for this composite consent, and an independently advanced knowledge pointer is not a governed answer. Native publication precedes Core-last activation; the response retains the Bound Release and citations.

Source Approval, caller data authorization, business review, and publication admission remain separate decisions. None is inferred from another.

## 5. Query the pinned admitted result

Call `query_data` with the `project`, source `source_task_id`, a supported native `operation`, and its native `request` object:

- `get_metric` or `query_metrics` for governed metrics;
- `query_detail` for governed detail;
- `query_records` for bounded records;
- `define_metric` for an explicitly ungoverned ad-hoc definition.

Before constructing any native catalog, the adapter resolves the complete effective source set in the current admission and checks the caller's current grant for that exact set. A project containing even one unauthorized source is refused before catalog construction. The service identity cannot be borrowed for this check.

The answer preserves the native governance label, rows, period/unit/caveat information, mandatory context and citations, plus the pinned commit and source digest. Governed means admitted, not independently value-attested. Unsupported prerequisites or operations return an actionable refusal, never a plausible number or raw-SQL/mutable-root fallback.

For the direct local operator commands and their human-only Source Approval and Git Admission boundaries, see [Git-backed authoring](git-authoring.md).
