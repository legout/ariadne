# Ariadne

**Governed metrics for AI agents.** Ariadne sits between your data and your AI agent
and makes sure the numbers coming back are the numbers your business agreed on.

When an agent writes SQL directly against a database (text-to-SQL), it guesses: which
table, which join, which filter, which definition of "revenue". Two runs of the same
question can return different answers, and nothing tells the agent that cancelled orders
must be excluded or that the currency changed in March. Ariadne replaces the guessing
with a governed catalog:

- A **semantic layer** holds the one canonical definition of each metric, written in
  the open [OSI](https://ossie.apache.org/) YAML format. Ariadne compiles these to SQL
  itself and executes them read-only — no agent ever hand-writes a query for a governed
  number.
- A **context layer** holds the business knowledge around those metrics — policies,
  table caveats, provenance — as plain version-controlled Markdown. Every governed
  answer carries its caveats with it, so the agent reports "revenue was X *— excluding
  cancelled orders, per policy*" instead of a bare number.

Agents talk to Ariadne over [MCP](https://modelcontextprotocol.io/), the standard tool
protocol — pi, Claude, and any other MCP-capable agent can connect directly.

## What you get

### For querying agents

- **Five MCP tools** covering the full question lifecycle (see below) — governed answers
  first, with a safe path for anything not yet modeled.
- **Caveats attached to every number.** Governed answers include the full text of every
  business policy the metric cites. Ungoverned answers are clearly labeled
  `governed: false`.
- **Fan-out protection.** Ad-hoc queries are checked for grain-preserving joins *before*
  execution, so one-to-many joins can't silently inflate totals — a classic way
  text-to-SQL agents produce wrong-but-confident numbers.

### For data owners

- **AI-assisted authoring, human gate.** One command profiles your databases and drafts
  the entire metric catalog and context pages into a `staging/` area. Nothing is ever
  served until a human reviews and promotes it.
- **Everything is files.** Metrics are YAML, business knowledge is Markdown. Review in
  pull requests, diff definitions, roll back with git. No server database to migrate.
- **Self-improving catalog.** When an agent answers an unmodeled question, its working
  definition is automatically staged as a proposal — good ad-hoc answers become
  governed metrics through the same human review.
- **Document ingestion.** Feed existing data dictionaries, PDFs, or Office documents in;
  get typed, provenance-cited proposals out, staged for review.

### For everyone

- **Lightweight.** A Python package plus embedded DuckDB. No API gateway, cache cluster,
  or refresh workers to operate.
- **Permissive runtime.** Only MIT/Apache-licensed dependencies — no AGPL, no proprietary
  engine.

## How it works

```text
 your data ──▶ profile ──▶ author (AI) ──▶ staging/ ──▶ human review ──▶ served catalog
  (many sources)        drafts everything     nothing serves              metrics + policies
                                                   from here                       │
                                                                                   ▼
                                              AI agent ◀── MCP ── Ariadne compiles the metric
                                               to SQL, checks it, runs it read-only,
                                               returns the number + its business caveats
```

1. **Register your sources** in one `ariadne.yaml` file.
2. **Profile & author**: `ariadne-author` inspects the actual data and combines it with
   your seed notes (the rules statistics can't see) to draft the catalog into `staging/`.
3. **Review & promote**: a human reads the staging area, then `ariadne-promote` merges
   approved artifacts into the served catalog and marks them verified.
4. **Query**: your agent connects over MCP. Governed metrics are compiled, checked, and
   executed by Ariadne; business context is searched alongside.

## Quickstart

Requires Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/). Authoring uses an LLM —
set `OPENAI_API_KEY` (plus `OPENAI_BASE_URL` / `OPENAI_MODEL` if not using OpenAI
directly) in a `.env` file.

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e .
```

**See it end-to-end** on a bundled example (seeds a demo shop, authors a catalog with a
live LLM, pauses for your review, then serves it):

```bash
examples/retail-demo/demo.sh
```

**Point it at your own data:**

```bash
ariadne-init my-project && cd my-project   # scaffold registry, seed notes, MCP config
# edit ariadne.yaml (your sources) and data/seed_notes.md (your business rules)
ariadne-author --sources ariadne.yaml --notes data/seed_notes.md
# review staging/, then:
ariadne-promote
ariadne-serve --sources ariadne.yaml        # starts the MCP server
```

The scaffolded `.mcp.json` wires your agent to `ariadne-serve`; restart the agent after
config changes. Installing the packaged skill (`ariadne-skill install --scope user`)
teaches your agent the whole workflow — query governed metrics first, respect the
staging boundary, report caveats with every number.

## Querying: the five MCP tools

| Tool | What the agent uses it for |
| --- | --- |
| `list_metrics` | Browse the governed catalog: metrics, descriptions, available dimensions |
| `get_metric` | Get a governed number — compiled SQL, executed read-only, caveats included |
| `search_context` | Look up business rules, policies, and table caveats before answering |
| `list_datasets` | See every table across all registered sources |
| `define_metric` | Answer an unmodeled question: draft a metric, pass the safety checks, run it read-only, label it `governed: false`, and auto-stage it as a proposal |

## Data sources

One read-only connection unifies every source; the agent addresses them as
`<source>.<table>`:

```yaml
sources:
  - name: shop
    type: sqlite
    path: data/shop.db
  - name: events
    type: parquet
    path: data/events/*.parquet      # globs become one table
    table: events
  - name: warehouse
    type: postgres
    connection_env: ARIADNE_PG_DSN   # credentials are env-var names, never inline
```

Supported: **SQLite, CSV, JSON, Parquet, Delta Lake, Iceberg, DuckLake, PostgreSQL** —
local files, `https://`, or `s3://`. Document ingestion (optional extra
`.[documents]`) covers Markdown, text, PDF, Word, PowerPoint, Excel, and HTML.

## How Ariadne compares

| Approach | What it is | Where Ariadne differs |
| --- | --- | --- |
| **Raw text-to-SQL agents** | The agent writes SQL directly against your database | No canonical definitions, no business rules, joins can silently inflate numbers. Ariadne compiles every governed metric itself and attaches the rules to the answer. |
| **Cube** | Mature headless-BI semantic layer you operate as a service | Cube is infrastructure: API gateway, caching, refresh workers, vendor-specific model format. Ariadne is a Python package with embedded DuckDB — no serving infrastructure — using open file formats (OSI YAML, Markdown). |
| **dbt MetricFlow** | Semantic layer inside the dbt ecosystem | Strong choice if you already run dbt; adopting it otherwise means adopting the whole dbt workflow. Ariadne stands alone and adds the agent-facing context layer and review gate. |
| **Wren MDL** | AI-oriented semantic modeling spec | Similar niche, but a vendor-specific spec with a weaker governance and join-safety story; Ariadne builds on the vendor-neutral OSI standard. |
| **Malloy** | Semantic modeling *language* from ex-Looker engineers | A language and toolchain, not a governed metric registry with business context; Ariadne's artifacts are plain YAML/Markdown with a human promotion gate. |

Ariadne is a good fit when AI agents need trustworthy, repeatable numbers from
heterogeneous data — and a human must stay in the loop on definitions. It is **not** a
BI dashboard, a transformation pipeline, or a high-concurrency metrics API; if you need
those, pair it with (or choose) the tools above.

## Technical details

The design decisions, specification, and research behind Ariadne live in the repo:

- Behavior spec: [project/specs/mvp-vertical-slice.md](project/specs/mvp-vertical-slice.md)
- Architecture decisions: [project/adr/](project/adr/)
- Domain vocabulary: [CONTEXT.md](CONTEXT.md) · Research: [project/research/](project/research/)
- Contributing: `python -m pytest` and `ruff check .` must stay green
