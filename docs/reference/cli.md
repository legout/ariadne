# CLI reference

This reference lists the Ariadne 0.3.0 command-line interfaces and their roles. Use `--help` on a command for its complete options. Examples assume the command is run from the data-project root.

## Select the project route

For a Git-managed project, use `--project DIR` on query commands. It selects the human-admitted snapshot and its approved source identity. A project without a valid admission fails rather than falling back to mutable files.

For a legacy staged project, use `--sources ariadne.yaml` or `--db PATH`; use `--served PATH` when the promoted artifacts are not unambiguously discoverable. These selectors are not interchangeable with `--project`.

The common query selectors follow the subcommand:

```bash
ariadne list-metrics --project .
ariadne get-metric gross_margin --project .
ariadne list-metrics --sources ariadne.yaml
```

## Project setup and diagnostics

| Command | Purpose |
| --- | --- |
| `ariadne setup --project DIR` | Scaffold or resume the selected project route; guide the operator through setup and show next steps. Does not initialize Git, approve sources, admit, or promote. |
| `ariadne setup --legacy --project DIR` | Explicitly choose a new legacy staged project. This is not a migration command. |
| `ariadne status --project DIR` | Read-only readiness and next-step report for a managed project. Use `--json` for structured output. |
| `ariadne status --sources FILE` | Read-only diagnostics for a legacy project. |
| `ariadne review --project DIR` | Operator review walkthrough for a managed proposal. |
| `ariadne review --served DIR` | Operator review walkthrough for a legacy Promotion target. |

See the [getting-started tutorial](../tutorials/getting-started.md) for the setup path and [Git-backed authoring](../how-to/git-authoring.md) for proposal and human-gate procedures.

## Query and discovery commands

| Command | Purpose |
| --- | --- |
| `ariadne search TEXT` | Read-only, grouped discovery across metrics, context pages, terms, and examples. |
| `ariadne list-metrics` | List governed metrics and available dimensions. |
| `ariadne get-metric NAME` | Execute a governed metric; accepts repeatable `--dimension` and optional `--start` / `--end`. |
| `ariadne list-datasets` | List queryable datasets. |
| `ariadne search-context TEXT` | Search context pages and policies. |
| `ariadne resolve-term TERM` | Resolve a documented term or exact field request; read-only guidance, never join authority. |
| `ariadne query-metrics --file REQUEST.json` | Query a multi-fact semantic graph. |
| `ariadne query-detail --file REQUEST.json` | Project fields through safe lookup paths from one root dataset. |
| `ariadne query-records --file REQUEST.json` | Select bounded records from one known table; no aggregation and `governed: false`. |
| `ariadne define-metric --file REQUEST.json` | Try an ad-hoc definition through the compile/safety path; result remains `governed: false` and may be staged as a proposal. |
| `ariadne search-examples TEXT` | Find labeled Answer Examples; these are method references, not cached answers. `--include-sql` opts into returned SQL provenance. |
| `ariadne save-example --file REQUEST.json` | Submit a confirmed Answer Example draft for the separate operator review path. |

The `ariadne` CLI prints JSON for query operations. Many commands accept `--file` or read the request from standard input when the file is omitted. Check `ariadne COMMAND --help` for the exact request shape and supported options.

## Authoring and human-only commands

`ariadne-authoring` is the proposal interface for authoring agents and operators. Its commands cover proposal creation, source proposals, inputs, typed artifact edits, validation, review, and context operations. See [Git-backed authoring](../how-to/git-authoring.md) for the full sequence.

The following decisions remain local, human-only operations; they are not exposed as agent/MCP tools:

- `ariadne-authoring approve-sources`
- `ariadne-admit`
- `ariadne-authoring reconcile`, `import-legacy`, and `enrich-legacy`
- `ariadne-promote` for a legacy staged project
- `ariadne-example-review` for Answer Examples

## Document ingestion

`ariadne-ingest` stages document-derived proposals; it does not serve them automatically. Markdown and text are handled natively. PDF, Office, HTML, and other supported conversion formats require the optional `ariadne-data[documents]` extra.

`ariadne-ingest --verbatim` creates a draft Reference from the converter's Markdown output without a model call. Verbatim mode cannot be combined with `--reconcile`.

## MCP registration modes

MCP registers query and authoring tools over the same core. Startup selects a combined or role-restricted toolset:

```bash
python -m ariadne.serve --project DIR
python -m ariadne.serve --project DIR --toolset analyst
python -m ariadne.serve --project DIR --toolset authoring
ariadne-analyst-mcp --project DIR
ariadne-authoring-mcp --project DIR
```

These registrations do not expose source approval, admission, reconciliation, legacy import/enrichment, Promotion, or Answer Example review.

## Optional transports and packages

- Core local interface: install `ariadne-data`.
- MCP server: install `ariadne-data[mcp]`, then run `ariadne-serve`; stdio is local. HTTP is opt-in and requires operator configuration.
- Conversational Python backend: install `ariadne-agent` separately. See the [Agent API README](../../ariadne-agent/README.md).

See [Docker MCP](../how-to/docker-mcp.md) for a private container setup. Installing an adapter does not change the human governance gates.
