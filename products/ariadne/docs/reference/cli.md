# CLI reference

One executable, `ariadne`. Commands run from a project root; pass `--project DIR` elsewhere and `--json` for one JSON value. Run `ariadne COMMAND --help` for exact flags. The removed per-purpose executables (`ariadne-authoring`, `ariadne-validate`, `ariadne-serve`, `ariadne-init`, `ariadne-admit`, `ariadne-skill`, `ariadne-analyst-mcp`, `ariadne-authoring-mcp`) and `ariadne setup` do not exist; schema refresh is the `authoring_refresh_schema` MCP tool only (spec 0040).

## Author

| Command | Purpose |
| --- | --- |
| `ariadne init [DIR] [--yes]` | Scaffold a project. Never configures Git, approves or admits. |
| `ariadne add TARGET [--name N] [--type T] [--storage S]` | Declare a source (file, URL, or Postgres DSN variable name) in the active draft. Inert. |
| `ariadne draft status` | The active draft's generation and stale state. |
| `ariadne draft edit FILE` | Apply one typed edit file (`model`, `graph`, `seed_notes`, `contract`, `pages`, `sources`, `source_change`). |
| `ariadne draft rebase` | Rebase a stale draft onto the served state. Human decision. |
| `ariadne draft discard [--stale]` | Discard the draft. Human decision. |
| `ariadne validate` | Validate the exact final revision against the granted sources. |
| `ariadne diff [--full]` | The draft against the served state. |
| `ariadne preview METRIC [--by DIM] [--filter F]` | Run a metric from the draft; `governed: false`. |
| `ariadne approve [--confirm-mapping SEL]` | Interactive, terminal only. Source approval first, then calculation approval. |
| `ariadne migrate` | Ossie 0.2 to 0.3 into the active draft. |

## Query and discovery

| Command | Purpose |
| --- | --- |
| `ariadne status` | Offline: served revision, approval, draft state. Opens no source. |
| `ariadne metrics` | List governed metrics. |
| `ariadne query METRIC [--by DIM] [--filter F]` | Governed metric query. |
| `ariadne detail [--file REQUEST.json]` | Governed detail query through safe lookups (JSON request, stdin if no file). |
| `ariadne datasets` | Queryable datasets from the approved live catalog (opens sources). |
| `ariadne search TEXT [--limit N]` | Read-only discovery over metrics, pages, terms and examples. |
| `ariadne page PATH` | Read one admitted context page. |
| `ariadne profile` | Profile the approved served sources. |

Ad-hoc metrics, record queries, term resolution and answer examples are MCP tools (`define_metric`, `query_records`, `resolve_term`, `search_examples`, `save_example`), not CLI commands. Ad-hoc results are `governed: false` and not saved.

## Skill and server

| Command | Purpose |
| --- | --- |
| `ariadne skill path\|install\|status` | The packaged agent skill. `status` reports `ok`/`drift`/`absent` per target; fix drift with `ariadne skill install [--scope project] [--agent pi\|claude\|hermes]`. |
| `ariadne serve [--toolset analyst\|authoring\|combined] [--project DIR] [--http ...]` | The MCP server (needs `ariadne-data[mcp]`). Stdio by default; HTTP is opt-in. |

## Human-only decisions

`approve`, `draft rebase` and `draft discard` are human decisions: `approve` refuses without an interactive terminal, and no MCP tool exposes any of them. A commit, a validation result or a successful query is never approval.

## Documents

There is no document CLI. The `authoring_inputs` MCP tool reads documents named relative to `<project>/data/docs/` and needs an active draft; it returns resource path, sha256 digest and bounded text parts. PDF/DOCX need `ariadne-data[documents]`. `data/*` is git-ignored, so originals are not versioned.

## Optional packages

- `ariadne-data[mcp]` adds the MCP transport.
- `ariadne-data[documents]` adds PDF/DOCX converters.
- `lumio-wiki` is the mandatory Lumio SDK pairing; it owns graph traversal, ingest and publishing of a general knowledge base.

DuckDB source extensions and storage credentials remain host prerequisites.
