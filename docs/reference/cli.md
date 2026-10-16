# CLI reference

This reference describes the Git-only Core interfaces. Examples assume commands run from a project root; use an explicit project path when running elsewhere.

## Project setup and route

`ariadne-init DIR` scaffolds a new project. It writes Seed Notes, the source-registry template, an operator pointer page and ignore rules. It does not initialize or configure Git, approve sources, admit a revision, or import existing staged state. `--with-mcp` opts into an MCP config; `--force` only overrides the project-manifest check and never overwrites existing scaffold files.

Configure Git yourself, then start a revision-checked proposal with `ariadne-authoring start --project DIR`. Durable project queries are project-bound and require a valid human admission:

```bash
ariadne status --project .
ariadne list-metrics --project .
ariadne get-metric gross_margin --project .
```

There is no plain-root serving route. The former `--served`, `--sources` and `--db` query selectors, staged bundle workflow, Promotion and legacy import/enrichment commands are not supported.

`ariadne setup --project DIR` is read-only with respect to authority and Git configuration: it may scaffold, inspect filenames and print operator handoffs, but it never runs `git init/config`, opens a source, approves sources, or admits. `ariadne status --project DIR [--json]` reports Git prerequisites, proposals, source approval, admission, and readiness without connecting to sources. `ariadne review --project DIR [--proposal ID]` is an operator walkthrough for one Git proposal; without an ID it lists pending proposals. A terminal prompt does not establish authenticated human identity.

## Query and discovery

| Command | Purpose |
| --- | --- |
| `ariadne search TEXT --project DIR` | Read-only grouped discovery over admitted metrics, context, terms, and Examples. |
| `ariadne list-metrics --project DIR` | List governed metrics and dimensions. |
| `ariadne get-metric NAME --project DIR` | Execute a governed metric; supports repeatable `--dimension` and optional `--start` / `--end`. |
| `ariadne list-datasets --project DIR` | List queryable datasets from the approved source identity. |
| `ariadne search-context TEXT --project DIR` | Search the admitted context snapshot. |
| `ariadne resolve-term TERM --project DIR` | Resolve an admitted term or field request; guidance does not authorize joins. |
| `ariadne query-metrics --file REQUEST.json --project DIR` | Query the admitted multi-fact graph. |
| `ariadne query-detail --file REQUEST.json --project DIR` | Project fields through safe lookups from one root dataset. |
| `ariadne query-records --file REQUEST.json --project DIR` | Select bounded records from one known table; no aggregation and `governed: false`. |
| `ariadne define-metric --file REQUEST.json --project DIR` | Run an ephemeral ad-hoc metric; result is `governed: false` and `persistence: {status: not_saved}`. |
| `ariadne search-examples TEXT --project DIR` | Find admitted Example method references; `--include-history` and `--include-sql` opt into labeled history and SQL provenance. |
| `ariadne save-example --file REQUEST.json --project DIR` | Save an explicitly confirmed Example to a Git proposal; no separate review store. |

The local CLI emits one JSON result per successful operation and one JSON error object on failure. Request commands accept `--file` or standard input; consult `ariadne COMMAND --help` for exact request shapes. Ad-hoc results are not retained automatically. To keep a definition or Example, use revision-checked proposal edits/saves, validate and review the candidate, then stop for human admission.

## Git Authoring and human-only decisions

`ariadne-authoring` supports proposal start/read/edit, source proposal, inputs, schema refresh, validation, review, context resolution, and bounded mapping inspection. Every mutation targets an explicit proposal and current revision.

The following decisions remain local and human-only; they are not MCP tools:

- `ariadne-authoring approve-sources --project DIR --proposal ID --revision REV --source-digest DIGEST` grants permission for the exact resolved source identity.
- `ariadne-admit --project DIR --proposal ID --revision REV --reviewed-digest DIGEST --confirm` admits the exact reviewed and validated revision (optional mapping confirmations must be explicitly selected).
- `ariadne-authoring reconcile` records a permitted clean local rebase/merge after the admitted baseline advances; it never merges or resets automatically.

A Git commit, validation result, proposed source, authored status field or successful query is not source approval or admission. See [Git-backed authoring](../how-to/git-authoring.md) and the [Git-only route reference](git-authoring-migration.md) for the complete sequence.

## Document ingestion and static validation

`ariadne-ingest DOC... --project DIR --proposal ID --expected-revision REV` reads operator-authorized external document references and writes authored pages into that proposal revision. `--verbatim` preserves converted text without a model call; `--reconcile` compares against the immutable admitted base and is mutually exclusive with `--verbatim`. Original documents remain external; Core has no upload/archive store.

`ariadne-validate ARTIFACT_DIR` performs source-free compile checks on an explicit artifact directory. Its result is partial structural evidence only: it does not open sources, perform live validation, approve sources, or admit content. Live validation is revision-bound through `ariadne-authoring validate` after human source approval.

## MCP

MCP binds one locally selected project with `--project DIR`. Choose `combined`, `analyst` or `authoring` at startup:

```bash
python -m ariadne.serve --project DIR
python -m ariadne.serve --project DIR --toolset analyst
python -m ariadne.serve --project DIR --toolset authoring
ariadne-analyst-mcp --project DIR
ariadne-authoring-mcp --project DIR
```

No tool argument selects another project, worktree, source identity, source approval or admission. Stdio is the default; HTTP is opt-in. Installing an adapter does not change the human governance gates.
