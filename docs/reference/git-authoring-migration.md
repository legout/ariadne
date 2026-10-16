# Git-only authoring and route reference

Core exposes one durable authoring route: revision-checked Git proposals followed by explicit human approval and admission. Project queries and discovery use only the exact human-admitted snapshot. This reference describes the supported contract; it is not a migration tool.

## Project route

Create a fresh project scaffold with `ariadne-init DIR`, initialize and configure Git yourself, then use `ariadne-authoring start --project DIR`. Initialization, Git configuration, source permission and admission remain separate operator decisions. Core does not import staged artifacts or old local state; existing files are never silently reset or adopted.

Public query and discovery entry points are project-bound:

- `ariadne --project DIR` and `QueryRuntime.open_project(DIR)` require a valid Git admission for governed queries.
- `DiscoveryRuntime.open_project(DIR)` exposes only admitted context; without admission it returns no project content.
- Plain artifact roots and the former `--served`, `--sources` and `--db` query selectors are not serving routes. Direct runtime construction is not a supported public API.
- `ariadne status --project DIR` is read-only. `ariadne setup --project DIR` may scaffold and report handoffs but never runs `git init/config`, approves sources or admits a revision.

## Durable authored content

`ariadne-authoring start` creates an isolated proposal. Typed artifact edits and source declarations require the proposal's current revision; stale edits refuse. Source declarations are inert until a human approves the exact resolved source identity. Approved inputs may then be measured, and candidate artifacts are validated and reviewed against exact revisions. `ariadne-admit --confirm` is the human-only gate for the reviewed, validated revision. A commit, validation result, metadata field or Git source declaration is not admission or source permission.

Examples and ingested pages are artifacts in the same candidate and admitted snapshot as Policies, models and other authored content. Example saving is explicit and creates an unreviewed candidate draft; there is no separate Example review store. Document originals remain operator-controlled and external to the artifact snapshot; Core retains the authored page and exact source identity/digest, not an upload or archive copy.

Ad-hoc `define-metric` results are ephemeral (`governed: false`, `persistence: {status: not_saved}`). To retain a definition, use an explicit revision-checked model/page edit in a Git proposal. `ariadne-ingest` likewise targets a selected proposal revision; it does not write a staging tree or admit the result.

## Human-only operations

The local operator remains responsible for:

- approving the exact source identity with `ariadne-authoring approve-sources`;
- admitting a reviewed and validated revision with `ariadne-admit --confirm` (including any explicit mapping confirmation);
- recording a permitted local rebase/merge with `ariadne-authoring reconcile` when the admitted baseline advances.

These commands are not registered as MCP tools. Core does not expose staged-bundle submission, legacy import/enrichment, Promotion, or a separate Example-review command.

## MCP

MCP binds one locally selected project with `--project DIR`. `combined`, `analyst` and `authoring` toolsets register the corresponding project query/discovery or Git Authoring operations. No tool argument selects another project, source identity, worktree, approval, or admission.
