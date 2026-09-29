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

Agents query Ariadne through the local `ariadne` command line — no server to run,
no extra setup. Ariadne also speaks [MCP](https://modelcontextprotocol.io/), the
standard tool protocol, as an optional extra (`ariadne[mcp]`) for remote or
host-integrated tool registration.

## What you get

### For querying agents

- **Local commands** covering the full question lifecycle (see below) — governed answers
  first, with a safe path for anything not yet modeled, plus saved answer examples as
  labeled method references. No server required.
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
- **Bring your own agent.** In harness-led authoring, your agent's *own* model drafts
  the catalog from measured profiles and converted documents (`ariadne-authoring`) —
  no server-side LLM. Source access and Promotion stay human decisions.
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
                                    AI agent runs `ariadne` (local) or connects over MCP:
                                               Ariadne compiles the metric
                                               to SQL, checks it, runs it read-only,
                                               returns the number + its business caveats
```

1. **Register your sources** in one `ariadne.yaml` file.
2. **Profile & author**: `ariadne-author` inspects the actual data and combines it with
   your seed notes (the rules statistics can't see) to draft the catalog into `staging/`.
   Or let your own agent's model do the drafting with `ariadne-authoring` (see
   "Harness-led authoring" below) — either way, a human reviews and promotes.
3. **Review & promote**: a human reads the staging area, then `ariadne-promote` merges
   approved artifacts into the served catalog and marks them verified.
4. **Query**: your agent runs `ariadne` locally against the promoted catalog — or
   connects over MCP with the optional extra.

## Quickstart

Requires Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/). Authoring uses an LLM —
set `OPENAI_API_KEY` (plus `OPENAI_BASE_URL` / `OPENAI_MODEL` if not using OpenAI
directly) in a `.env` file.

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e .
source .venv/bin/activate
```

**See it end-to-end** on a bundled example (seeds a demo shop, authors a catalog with a
live LLM, pauses for your review, then queries a governed metric locally):

```bash
examples/retail-demo/demo.sh
```

**Point it at your own data:**

```bash
ariadne-init my-project && cd my-project   # scaffold registry, seed notes (local-first)
# edit ariadne.yaml (your sources) and data/seed_notes.md (your business rules)
ariadne-author --sources ariadne.yaml --notes data/seed_notes.md
# review staging/, then:
ariadne-promote
ariadne list-metrics --sources ariadne.yaml      # query locally — no server needed
ariadne get-metric gross_margin --sources ariadne.yaml
```

Installing the packaged skill (`ariadne-skill install --scope user`) teaches your agent
the whole workflow — query governed metrics first, respect the staging boundary, report
caveats with every number.

### Harness-led authoring — bring your own agent

`ariadne-author` above drafts using an LLM configured on the host (`.env`). If your
agent harness has its own model, it authors instead through the local
`ariadne-authoring` commands — base install only, no OpenAI-compatible endpoint, no
extra credential:

```bash
ariadne-init my-project && cd my-project
# 1. agent: propose source registry entries (inert data — nothing is opened yet)
ariadne-authoring propose-sources --file sources-proposal.yaml
# 2. HUMAN operator (never the agent): review the digest, install into ariadne.yaml
#    ariadne-authoring approve-sources --digest <digest>
# 3. agent: read the measured profile (null until step 2) and converted documents
#    from data/docs/ (allowed roots live in ariadne.yaml's documents: section)
ariadne-authoring inputs --document policy-notes.md
# 4. agent's own model drafts Seed Notes + OSI + OKF, submits, repairs on errors
#    (3 rounds max; each repair needs the current digest as --base-digest)
ariadne-authoring submit --file submission.json   # cites its document references
# 5. agent inspects and reports the exact digest, then STOPS
ariadne-authoring review
# 6. HUMAN (never the agent): ariadne-promote on the reviewed digest
```

Documents are pre-staged by the operator in `data/docs/` (or another configured
root); PDF/Office/HTML conversion uses the optional `.[documents]` extra, and
inputs are bounded (converted text arrives in parts). Metrics without an
independent expected-value oracle are staged with `attestation: pending` —
`governed: true` means Promoted, not independently value-attested.

**Optional: stdio MCP for authoring.** With the `mcp` extra installed (see below),
the same local stdio server exposes the five authoring tools
(`authoring_propose_sources`, `authoring_inputs`, `authoring_upload_document` for
bounded ≤5 MiB uploads, `authoring_submit_bundle`, `authoring_review_bundle`) with
identical contracts — plus the five query tools. Stdio is local and needs no
token; the server runs for one project root. Source approval and Promotion are
never exposed as tools.

**Optional: MCP.** The base package is local-first and needs no server; MCP registers the
same operations as tools when you want them. Install the extra into the same Python
environment as `ariadne`, from the Ariadne package checkout (the directory containing
`pyproject.toml`):

```bash
uv pip install --python .venv/bin/python -e '.[mcp]'
```

Then, from the initialized project root, opt in to its registry-aware `.mcp.json` (an
existing file is never overwritten) and start the server:

```bash
ariadne-init --with-mcp .
ariadne-serve --sources ariadne.yaml
```

The scaffolded `.mcp.json` wires your agent to `ariadne-serve`; restart the agent after
config changes.

## Querying: the local commands

All commands print one JSON value; the common options (`--sources`/`--db`, `--served`) follow
the subcommand. The CLI finds promoted artifacts in the working directory or `./served`.
MCP registers the same operations as tools when the `mcp` extra is installed.

| Command | What the agent uses it for |
| --- | --- |
| `ariadne list-metrics` | Browse the governed catalog: metrics, descriptions, available dimensions |
| `ariadne get-metric NAME` | Get a governed number — compiled SQL, executed read-only, caveats included |
| `ariadne search-context QUERY` | Look up business rules, policies, and table caveats before answering |
| `ariadne list-datasets` | See every table across all registered sources |
| `ariadne define-metric` | Answer an unmodeled question: draft a metric (JSON via `--file` or stdin), pass the safety checks, run it read-only, label it `governed: false`, and auto-stage it as a proposal |
| `ariadne search-examples QUERY` | Find explicitly saved answer examples — labeled references (draft/stable, staleness, provenance) for checking a method, never cached answers; never executes a query |
| `ariadne save-example` | Save one answer example after the user explicitly confirms the bounded record (question, interpretation, method, result excerpt, self-declared attestation); stages a draft under `staging/answer_examples/` for operator review |

Saved examples are references, not caches: a similar question still compares dates, filters,
grain and cited policies, and the answer is always produced fresh by the runtime. Reviewing
submissions is an operator command (`ariadne-example-review`), never an agent action.

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
