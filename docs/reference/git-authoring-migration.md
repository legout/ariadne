# Git authoring and legacy migration reference

This reference records how Git-managed proposals relate to the retained staging/Promotion route. For the operator procedures, see [How to author a Git-managed project](../how-to/git-authoring.md).

## Route distinctions

| Legacy staged route | Git-managed route |
| --- | --- |
| Query an explicit artifact root using `--sources` / `--db` and, when needed, `--served`. | Query the pinned human-admitted snapshot using `--project DIR`. Missing admission is an error; there is no fallback to mutable files. |
| Runtime constructors with explicit roots: `QueryRuntime(sources=..., semantic=..., context=..., staging=...)` and the `AriadneRuntime` / `serve.Facade` aliases. | Project factory `QueryRuntime.open_project(project)` / `ariadne --project DIR` resolves the pinned admitted snapshot and its operator-approved source identity. Explicit legacy constructors keep working for legacy roots. |
| `ariadne-authoring submit --file submission.json` submits a complete staged bundle. | Start a Git proposal and use revision-checked typed `ariadne-authoring edit` calls; unchanged artifacts are inherited from the base. |
| Repair chaining uses `submit --base-digest DIGEST` — the current submission digest. | Edits use the current candidate revision (`--expected-revision`); stale revisions are refused. The bounded repair policy is per proposal. |
| Review the staged bundle at its exact content digest. | `ariadne-authoring review` reports the exact base/candidate revisions and a review digest bound to that identity. Reading the report is not admission. |
| Human `ariadne-promote` moves staged artifacts to the served catalog. | Human `ariadne-admit` binds admission to the exact reviewed and validated revision, then publishes the pinned snapshot. |
| `ariadne-author` can profile and draft to `staging/`. | `python -m ariadne.author --git ...` drafts into an unadmitted Git proposal. The legacy `--staging` route remains available for legacy projects. |
| `staging/authoring/bundle-state.json` is local staging state. | Validation evidence is bound to the exact final commit; a legacy `validated` marker is not admission evidence. |
| A changed baseline is handled through the legacy workflow. | Human `ariadne-authoring reconcile` records a clean new HEAD and invalidates evidence from the old revision; it never merges automatically. |

Runtime constructors with explicit roots and legacy selectors remain available for legacy projects. The managed project factory and `--project DIR` route select the admitted snapshot and approved source identity. Do not mix selectors or expect one route to interpret the other's state.

## MCP startup, legacy and managed

MCP startup maps the same way: the managed route binds one project, and combined or role-restricted toolsets are selected with `--toolset`. Legacy projects keep their existing registration flags.

```bash
python -m ariadne.serve --project DIR                    # combined (default): Query + Authoring
python -m ariadne.serve --project DIR --toolset analyst   # Query operations only
python -m ariadne.serve --project DIR --toolset authoring # the authoring_ Git contract only
```

## Stores and workflows that remain separate

Git authoring does not absorb or automatically admit these workflows:

- **Legacy Promotion:** `ariadne-promote` continues to serve staged projects and does not create a Git admission record.
- **Standalone document ingestion:** `ariadne-ingest` stages context pages and retains its separate human Promotion gate. Bringing a page into a Git proposal requires an explicit edit/import step.
- **Ad-hoc metrics:** `ariadne define-metric` creates `governed: false` drafts in its own staging store.
- **Answer Examples:** saving and operator review use their own store and gate; they are not part of Git admission.

A migration does not coalesce these pending stores or change their review paths.

MCP role entry points and the list of human-only operations are in the [CLI reference](cli.md).
