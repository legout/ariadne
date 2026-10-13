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
standard tool protocol, as an optional extra (`ariadne-data[mcp]`) for remote or
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
  no server-side LLM. Source access, admission and Promotion stay human decisions.
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
   Or let your own agent's model draft through `ariadne-authoring` Git proposals (see
   "Harness-led authoring" below) — either way, a human reviews, and only a human
   promotes or admits.
3. **Review & promote (legacy staged project)**: a human reads the staging area, then
   `ariadne-promote` merges approved artifacts into the served catalog and marks them
   verified. **Git-managed project**: a human admits the exact reviewed, validated
   candidate revision with `ariadne-admit --confirm` (see
   [docs/how-to/git-authoring.md](docs/how-to/git-authoring.md)).
4. **Query**: your agent runs `ariadne` locally against the promoted catalog (`--served`)
   or the pinned admitted snapshot (`--project DIR`) — or connects over MCP with the
   optional extra.

## Quickstart

Requires Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/). Install the core CLI
from PyPI — no server or conversational host required:

```bash
uv tool install ariadne-data
# Optional conversational host (not required for the core CLI):
uv tool install ariadne-agent
```

**Version boundary:** the currently published **0.2.0** does not include
`ariadne setup` or `ariadne status`. The wizard walkthrough below describes this
**unreleased candidate**, verified from an installed candidate wheel; it is not a
claim that PyPI already ships these commands. With 0.2.0, scaffold using
`ariadne-init --git my-project` and follow the explicit Git authoring commands below.
After a separately authorized release, the PyPI install above will provide the wizard.

### Operator setup (unreleased candidate)

```bash
ariadne setup --project my-project --agents --agent pi
cd my-project
# HUMAN: setup scaffolds files, NOT a Git repository. Prepare your own repository:
git init
git config user.name "Your Name"       # repository-local, never global
git config user.email "you@example.org"
# Put your data under data/; edit data/seed_notes.md with the owner:
# domain, row grain, business rules, desired metrics; clarify unknown meanings.
ariadne setup --project . --agents --agent pi
```

New projects default to Git-managed proposals; an existing route is preserved,
never migrated. An ambiguous scaffold requires your route choice. Setup detects
filenames only (`.db`, `.sqlite`, `.csv`, `.json`, `.parquet`), offers editable
hints, and asks before declaring **inert** sources. Postgres declarations name a
DSN environment variable (`connection_env`), never the credential value. Setup
prints the exact source-approval command with the real proposal ID, revision and
complete resolved digest, then pauses the source/authoring pipeline. **Only the
human operator runs that command** — setup never approves, admits, promotes,
reconciles, initializes Git or configures identity, even at a terminal.

`--no-input` (also non-terminal input/output) scaffolds/detects/reports only; it
never accepts a source list or runs authoring. `--agents` needs an explicit
`--agent` non-interactively. Project scope is the default and installs inside
`--project DIR`, even from another cwd. Choose `--agent pi`, `claude` or `hermes`
for a canonical `.agents/skills/ariadne` copy plus the respective project host
link `.pi/skills/ariadne`, `.claude/skills/ariadne` or `.hermes/skills/ariadne`.
`--agent universal` is universal-only, not host activation. `--scope user` must be
explicit. Detection, diagnostics and skill installation make no network calls.

### From declarations to the first governed answer

For managed projects, use your harness's own model with the packaged skill: no
second LLM credential. If you skipped interactive declarations, write
`sources.yaml` as a registry-shaped `sources:` list, then use the same existing
commands setup composes:

```bash
ariadne-authoring start --project .     # returns ID and candidate revision REV
ariadne-authoring propose-sources --project . --proposal ID --expected-revision REV --file sources.yaml
# HUMAN: review the resolved sources, then run the exact command setup/the seam returned:
ariadne-authoring approve-sources --project . --proposal ID --revision REV --source-digest DIGEST
# Harness: measured inputs, seed-note/domain clarification, then typed artifact edits:
ariadne-authoring inputs --project . --proposal ID
ariadne-authoring edit --project . --proposal ID --expected-revision REV --file edit.json
ariadne-authoring validate --project . --proposal ID --expected-revision REV
ariadne-authoring review --project . --proposal ID
# HUMAN: inspect the exact review, use its final revision and reviewed digest:
ariadne-admit --project . --proposal ID --revision REV --reviewed-digest DIGEST --confirm
ariadne list-metrics --project .
ariadne get-metric YOUR_METRIC --project .   # a FRESH query of the pinned admitted snapshot
```

Use the returned revision after **each** edit/validation, not an old `REV`.
If setup already created a pending proposal, reuse its ID/revision rather than
starting a replacement. Validation/review are not admission. Setup's final status
preserves blockers: a successful scaffold/skill install is not a query-ready catalog.
`governed: true` means human-admitted/Promoted; `attestation: pending` is **not
independently value-attested**. Keep the returned Context/Policy caveats with every number.
The complete typed authoring sequence lives in
[docs/how-to/git-authoring.md](docs/how-to/git-authoring.md) and
[docs/how-to/context-knowledge.md](docs/how-to/context-knowledge.md).

For the retained staged route, use `ariadne setup --legacy --project my-project`
(candidate) or `ariadne-init my-project` (published 0.2.0). Propose sources with
`ariadne-authoring propose-sources --project . --file sources.yaml`; the human
runs the returned `ariadne-authoring approve-sources --project . --digest DIGEST`.
Then either follow the harness-led staged loop below, or explicitly select the
existing `ariadne-author --sources ariadne.yaml --notes data/seed_notes.md` run.
That optional run profiles authorized sources and sends profiles/notes to the
configured LLM (`OPENAI_API_KEY`, `OPENAI_MODEL`, optional `OPENAI_BASE_URL` in the
environment or `ARIADNE_ENV` file); setup discloses this network/data egress before
selection. It stages drafts only. A human reviews `staging/` and runs
`ariadne-promote`, then `ariadne list-metrics --sources ariadne.yaml` and
`ariadne get-metric YOUR_METRIC --sources ariadne.yaml`. Never promote unresolved
`review_needed` artifacts. Existing legacy projects are never converted by setup;
operator-only migration is documented in the Git authoring guide.

### Source development (separate from the PyPI install)

From the package checkout, not the data project:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e .
source .venv/bin/activate
# Bundled end-to-end demo: live configured LLM, human review, then a fresh query:
examples/retail-demo/demo.sh
```

For the candidate-wheel check: `uv build`, create a fresh venv with
`uv venv --python 3.12 /tmp/ariadne-wheel-venv`, then
`uv pip install --python /tmp/ariadne-wheel-venv/bin/python dist/ariadne_data-*.whl`.
Exercise the walkthrough with those installed console scripts, not the editable install.

### Harness-led authoring — bring your own agent

`ariadne-author` above drafts using an LLM configured on the host (`.env`). If your
agent harness has its own model, it authors instead through the local
`ariadne-authoring` commands — base install only, no OpenAI-compatible endpoint, no
extra credential. In a Git-managed project (scaffolded with `ariadne-init --git`, the
flow above) the agent drafts through isolated proposals; `ariadne-author --git` runs
the same drafting loop straight into an unadmitted proposal. The legacy staged route
below keeps working for non-Git projects:

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

**Optional: stdio MCP toolsets.** With the `mcp` extra installed (see below),
the same local stdio server exposes the role toolsets over one core — pick the
registration at launch: `python -m ariadne.serve --project DIR` (combined,
the default), `--toolset analyst` (the query tools `list_metrics`,
`search_context`, `get_metric`, `list_datasets`, `define_metric`,
`query_metrics`, `query_detail`, `query_records`, `resolve_term`,
`save_example`, `search_examples`), or `--toolset authoring` (the Git proposal contract:
`authoring_start_proposal`, `authoring_read_artifact`,
`authoring_edit_proposal`, `authoring_propose_sources`, `authoring_inputs`,
`authoring_upload_document` for bounded ≤5 MiB uploads,
`authoring_refresh_schema`, `authoring_validate_proposal`,
`authoring_inspect_mapping`, `authoring_resolve_term`,
`authoring_review_proposal`) with identical
contracts to the `ariadne-authoring` commands. Stdio is local and needs no
token; the server runs for one project root. Source approval, admission,
reconciliation, the legacy import/enrichment and Promotion are never exposed
as tools.

**Opt-in HTTP (issue #18).** `ariadne-serve --project DIR --http` serves the
same toolsets at `/mcp`, on loopback (`127.0.0.1`) by default. Every request,
including health/readiness checks, requires `Authorization: Bearer <token>`
from the server environment `ARIADNE_HTTP_TOKEN`. Missing/wrong tokens fail
before dispatch; the token never belongs in `ariadne.yaml`, responses or logs.
Stdio remains token-free and opens no HTTP listener.

**Compose/container binding (owner-approved 2026-10-10).** Add
`--http-container --http-host 0.0.0.0` to allow other containers to connect.
The default Compose service publishes no ports; put the MCP client or HTTPS
proxy on the same network. The separate loopback-only override is for a
host-side private HTTPS proxy such as Tailscale Serve. External clients still
require private HTTPS. This option is not deployment/exposure approval.

The SDK's DNS-rebinding protection stays enabled. Explicitly add the service
and proxy Host values using repeatable `--http-allowed-host` flags. For
clients sending an Origin header, add its exact origin with
`--http-allowed-origin`; requests without Origin need no origin entry.
Do not use blanket wildcards. The repository includes a non-root
[Dockerfile](Dockerfile), [Compose template](compose.yaml) and
[loopback override](compose.loopback.yaml). See
[Docker MCP with an external data project](docs/how-to/docker-mcp.md) for
owner permissions, stable Git/source paths, networking and the smoke check.
The project stays external and is mounted at the same absolute host/container
path; the image does not contain project data or credentials. A network client
uses `http://ariadne:8000/mcp` with the bearer token. A private HTTPS proxy
must preserve Authorization/MCP headers and streaming; configure it separately.

- `GET /healthz`: `200 {"status":"ok"}` when the HTTP process responds.
- `GET /readyz`: `200 {"status":"ready"}` for Authoring without requiring a
  catalog; Analyst/Combined require a usable metric catalog through the shared
  runtime's discovery/admission checks. Failures return only
  `503 {"status":"not_ready"}`, never exception details or project paths.
- Both accept HEAD and require the same bearer token. Readiness does not
  calculate metrics or test every source/graph operation. A lazy runtime may
  perform its existing bounded source initialization on the first ready check.

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
| `ariadne resolve-term TERM` | Resolve shared business terms and identifier knowledge (representations, exact field bindings, scope, ambiguity, claim/confirmation status) against the admitted context — read-only guidance, never join authority |
| `ariadne list-datasets` | See every table across all registered sources |
| `ariadne query-records` | Bounded record selection from one known table — the latest N rows, no aggregation: explicit filters/order/timestamp contract, `governed: false`, never staged, truthful requested-top-N completeness, and all-or-nothing overflow refusals with narrowing guidance |
| `ariadne define-metric` | Answer an unmodeled question: draft a metric (JSON via `--file` or stdin), pass the safety checks (ad-hoc SQL may read only registered catalog relations — file, network and table-function reads are refused before execution), run it read-only, label it `governed: false`, and auto-stage it as a proposal |
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
