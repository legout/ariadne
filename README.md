# Ariadne

Governed metrics for autonomous agents. An authoring agent profiles a database, combines
the profile with human seed notes, and drafts a full **Context Layer** (OKF v0.2 bundle:
tables, join references, policies, metrics, attested computations, skills) plus a
**Semantic Layer** (OSI YAML) into `staging/`. A human promotes them (`ariadne-promote`
— merge-only, records `verified`, regenerates indexes); agents then query via MCP:
`ariadne/render.py` (our own sqlglot compiler, ADR-0008) renders OSI to SQL, a
facade-owned read-only DuckDB connection
executes it, and **no computation ever bypasses the compile gate** — including
agent-drafted ad-hoc metrics (`define_metric`), which are grain-checked, executed
read-only, and auto-staged as promotion candidates.

Spec: [project/specs/mvp-vertical-slice.md](project/specs/mvp-vertical-slice.md) · research:
[project/research/](project/research/) (engine evidence in
[datus-spike.md](project/research/datus-spike.md)) · decisions: [project/adr/](project/adr/).

## Setup

```bash
uv venv --python 3.12 .venv   # floor is CPython 3.12 (>=3.12; no upper cap since ADR-0008)
uv pip install --python .venv/bin/python -e ".[dev]"
```

The editable install registers console scripts — `ariadne-ingest`, `ariadne-author`,
`ariadne-validate`, `ariadne-serve`, `ariadne-promote`, `ariadne-init`, `ariadne-skill`,
`ariadne-profiler`. `ariadne-init [TARGET_DIR]`
scaffolds a fresh project's inputs (seed notes, an AGENTS.md pointer page,
`.env.example`, `.mcp.json` wired to `ariadne-serve --sources ariadne.yaml`, `.gitignore`,
empty `data/` + `data/docs/` for ingestible source
documents); the served layers are never scaffolded —
they arrive only via author + promote.

Live authoring credentials are read from `$ARIADNE_ENV` (default
`/home/volker/coding/ariadne/.env`, never committed): `OPENAI_API_KEY`,
`OPENAI_BASE_URL`, `OPENAI_MODEL`.

## Demo

```bash
examples/retail-demo/demo.sh --yes    # seed → author (live LLM) → promote → facade + scripted client
examples/retail-demo/demo.sh          # pauses for human promotion instead
```

## The facade — five MCP tools (stdio)

```bash
.venv/bin/python -m ariadne.serve --db examples/retail-demo/data/demo.db \
    --semantic semantic_layer --context context_layer
```

- `list_metrics()` — governed metrics with descriptions + available dimensions + routing hint
- `list_datasets()` — every table in the attached database (the agent's map of queryable data)
- `search_context(query)` — ranked matches over the served OKF bundle and draft proposals
- `get_metric(name, dimensions, range)` — governed rows + compiled SQL (`governed: true`);
  served models run the same compile/bind/grain gauntlet as the ad-hoc path
- `define_metric(definition)` — the ad-hoc path: agent-drafted metric → grain-preservation
  check → renderer compile → read-only execution → `governed: false` + auto-staged proposal

The repo ships a `.mcp.json` — pi (via `pi-mcp-adapter`) and any MCP-capable agent connect
to the facade directly; restart the agent after config changes.

## The packaged agent skill (ADR-0011)

The wheel ships an agent skill (`ariadne/skill_assets/`: SKILL.md + the grain-rubric
reference), version-locked to the package. Install it for your agents:

```bash
ariadne-skill install --scope user --agent pi   # ~/.agents/skills/ariadne + ~/.pi symlink
ariadne-skill install --scope project           # .agents/skills/ariadne in this project
ariadne-skill status                            # per-target drift vs the packaged skill
ariadne-skill path                              # print the packaged location
```

The `.agents/skills` directory is the cross-agent convention; `--agent pi|claude|hermes`
additionally wires the agent-specific dir as a symlink to it (copy + note where symlinks
are unavailable). Re-install refreshes. The skill owns the workflow (profile → author →
review staging → human promote → query) and the agent rules — per-project AGENTS.md
stays a pointer page (`ariadne-init` scaffolds one) with just the project facts.

Governed `get_metric` responses carry the rules with the number: a `context` field with
the full served OKF metric page plus the full bodies of every policy it cites — agents
report those caveats with every answer (ad-hoc `define_metric` responses carry
`context: null`).

## Sources — the `ariadne.yaml` registry (ADR-0010)

Every command takes its data sources from one declarative registry — a `sources:` block in
`ariadne.yaml` (scaffolded, commented-out, by `ariadne-init`). When the file declares sources,
all commands (`ariadne-serve`, `ariadne-author`, `ariadne-validate`, `ariadne-profiler`) use it
automatically; `--sources <file>` overrides, and the legacy `--db examples/retail-demo/data/demo.db` remains the
single-SQLite shorthand (catalog `demo`) for projects without a registry.

```yaml
sources:
  - name: demo            # addressable as demo.<table>
    type: sqlite
    path: examples/retail-demo/data/demo.db
  - name: events
    type: parquet
    path: data/events/*.parquet
    table: events        # globs: one view over the whole glob
  - name: raw_orders     # csv / json / parquet — local or https:// / s3:// (httpfs)
    type: csv
    path: data/orders.csv
  - name: lake
    type: delta           # also: iceberg, ducklake (DuckDB extensions)
    path: data/lake/orders
  - name: pg
    type: postgres
    connection_env: ARIADNE_PG_DSN   # env-var NAME only — resolved at runtime
```

The shared connection builder produces one read-only DuckDB session for all commands, so every
source is addressable as `<source>.<table>` and the compiler, grain guard, and audit operate
unchanged over the unified connection (`list_datasets()` reflects the full multi-source catalog).
Validation rejects unknown types, non-slug names, glob paths without a `table:`, and any inline
connection string — credentials are environment-variable references only (ADR-0010: never
committed; a missing variable fails with the variable name in the error). Live-fixture tests
cover sqlite/csv/json/parquet/delta; iceberg/ducklake/postgres/remote paths are covered by
exact statement-construction tests.

This repo itself runs multi-source: its `ariadne.yaml` declares the demo sqlite shop plus a
support-tickets parquet extract, and the profiler/author work across BOTH sources:

```bash
python examples/retail-demo/seed_db.py examples/retail-demo/data/demo.db            # source 1: demo (sqlite)
python examples/retail-demo/make_parquet_fixture.py            # source 2: support (parquet glob -> support.tickets)
.venv/bin/python -m ariadne.profiler --no-out     # profiles every table of every registered source
.venv/bin/python -m ariadne.author --sources ariadne.yaml --notes examples/retail-demo/seed_notes.md
```

`examples/retail-demo/demo.sh` does all of the above end-to-end (seed both sources → author over the
registry → promote → serve), and the served bundle then carries governed metrics over
`support.tickets` (ticket counts, average resolution hours) alongside the orders metrics.

## Document ingestion (ADR-0009)

`ariadne-ingest project/ingest-example.md` turns a document into typed OKF proposals without
the authoring loop: convert → LLM distill → per-type contract gate → stage under
`staging/context_layer/`. Classification follows the bundle taxonomy: `policies/` (owner
rules, transcribed verbatim), `tables/` (row meaning + declared grain), `references/` and
`references/joins/`; anything unclassifiable lands in `references/` tagged `ingest`.
Provenance is mechanical — every staged page cites its source in `sources[]`
(sha256-12 digest + absolute path + filename) and carries `generated: {by:
ariadne-ingest:<model>}` plus `status: draft`. Violating pages get at most 2 repair
rounds; a document that never passes the gate stages nothing.

- **Converters** (dispatch by extension): `.md`/`.txt` natively; `.pdf` via `liteparse`;
  `.docx`/`.pptx`/`.xlsx`/`.html` via `markitdown`; `.doc`/`.rtf`/`.epub`/`.csv`/`.odt`/
  `.ods`/`.odp`/`.xls` via `firecrawl-anydoc`. Install with
  `uv pip install -e ".[documents]"`; a missing converter fails just that document with
  the exact hint (the base install stays lightweight). Note: firecrawl-anydoc 0.1.3 ships
  no HTML reader, so `.html` is handled by markitdown (owner decision, rev 8 round).
- **Staging discipline**: writes go only under `staging/context_layer/` — never the
  served dirs, never `index.md`/`log.md` (promote owns bundle bookkeeping); name
  collisions suffix `-2`/`-3` atomically. Promote as usual: `python ariadne-promote`.
- **Credentials**: same `OPENAI_*` wiring as the author (`$ARIADNE_ENV`).

## Authoring, promotion, safety

- `python -m ariadne.author --db examples/retail-demo/data/demo.db --notes examples/retail-demo/seed_notes.md` — the ≤3-round
  author/validate loop; writes only under `staging/`
- `python -m ariadne.validate staging --db examples/retail-demo/data/demo.db` — `render()` compile gate + grain audit
  (declared-grain uniqueness, parent aggregate invariance, join-uniqueness guard incl. CTEs)
- `python ariadne-promote` — human promotion gate: merges staged → served (never wipes),
  appends `verified`, regenerates all `index.md`, appends `log.md`; idempotent
- `tests/test_evals.py` — golden question→value sets and the fan-out sentinel
  ([Datus-ai/Datus-agent#1426](https://github.com/Datus-ai/Datus-agent/issues/1426))

## Tests

```bash
.venv/bin/python -m pytest     # green incl. the joined-row-grain renderer-behavior test (ADR-0008)
.venv/bin/python -m ruff check .
```

## Dependencies & licensing

Compile engine: **our own sqlglot renderer** (`ariadne/render.py`, ADR-0008) over
`sqlglot` (MIT) — the runtime is **AGPL-free**: `datus-semantic-osi` and its
AGPL-3.0 transitive dependency `datus-metricflow` were removed from the
dependencies (spec rev 7; the datus engine remains documented in
[datus-spike.md](project/research/datus-spike.md) as the superseded mechanism and in
[ADR-0008](project/adr/0008-own-sqlglot-compiler-agpl-exit.md)). Remaining runtime
dependencies: `duckdb`, `mcp` (pinned `<2` — 2.x renames the FastMCP tool API),
`sqlglot`, `openai`, `pyyaml`. The proprietary `dosi-engine` (Elastic-2.0) was
evaluated and **not** adopted — see the engine correction in the
[research study](project/research/agentic-semantic-layer-architecture.md).
