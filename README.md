# Ariadne

Governed metrics for autonomous agents. An authoring agent profiles a database, combines
the profile with human seed notes, and drafts a full **Context Layer** (OKF v0.2 bundle:
tables, join references, policies, metrics, attested computations, skills) plus a
**Semantic Layer** (OSI YAML) into `staging/`. A human promotes them (`scripts/promote.py`
— merge-only, records `verified`, regenerates indexes); agents then query via MCP:
`ariadne/render.py` (our own sqlglot compiler, ADR-0008) renders OSI to SQL, a
facade-owned read-only DuckDB connection
executes it, and **no computation ever bypasses the compile gate** — including
agent-drafted ad-hoc metrics (`define_metric`), which are grain-checked, executed
read-only, and auto-staged as promotion candidates.

Spec: [docs/specs/mvp-vertical-slice.md](docs/specs/mvp-vertical-slice.md) · research:
[docs/research/](docs/research/) (engine evidence in
[datus-spike.md](docs/research/datus-spike.md)) · decisions: [docs/adr/](docs/adr/).

## Setup

```bash
uv venv --python 3.12 .venv   # floor is CPython 3.12 (>=3.12; no upper cap since ADR-0008)
uv pip install --python .venv/bin/python -e ".[dev]"
```

The editable install registers console scripts — `ariadne-author`, `ariadne-validate`,
`ariadne-serve`, `ariadne-promote`, `ariadne-init`. `ariadne-init [TARGET_DIR]`
scaffolds a fresh project's inputs (seed notes, `.env.example`, `.mcp.json` wired to
`ariadne-serve`, `.gitignore`, empty `data/`); the served layers are never scaffolded —
they arrive only via author + promote.

Live authoring credentials are read from `$ARIADNE_ENV` (default
`/home/volker/coding/ariadne/.env`, never committed): `OPENAI_API_KEY`,
`OPENAI_BASE_URL`, `OPENAI_MODEL`.

## Demo

```bash
scripts/demo.sh --yes    # seed → author (live LLM) → promote → facade + scripted client
scripts/demo.sh          # pauses for human promotion instead
```

## The facade — five MCP tools (stdio)

```bash
.venv/bin/python -m ariadne.serve --db data/demo.db \
    --semantic semantic_layer --context context_layer
```

- `list_metrics()` — governed metrics with descriptions + available dimensions + routing hint
- `list_datasets()` — every table in the attached database (the agent's map of queryable data)
- `search_context(query)` — ranked matches over the served OKF bundle and draft proposals
- `get_metric(name, dimensions, range)` — governed rows + compiled SQL (`governed: true`)
- `define_metric(definition)` — the ad-hoc path: agent-drafted metric → grain-preservation
  check → Datus compile → read-only execution → `governed: false` + auto-staged proposal

The repo ships a `.mcp.json` — pi (via `pi-mcp-adapter`) and any MCP-capable agent connect
to the facade directly; restart the agent after config changes.

## Authoring, promotion, safety

- `python -m ariadne.author --db data/demo.db --notes data/seed_notes.md` — the ≤3-round
  author/validate loop; writes only under `staging/`
- `python -m ariadne.validate staging --db data/demo.db` — Datus compile + grain audit
  (declared-grain uniqueness, parent aggregate invariance, join-uniqueness guard incl. CTEs)
- `python scripts/promote.py` — human promotion gate: merges staged → served (never wipes),
  appends `verified`, regenerates all `index.md`, appends `log.md`; idempotent
- `tests/test_evals.py` — golden question→value sets and the fan-out sentinel
  ([Datus-ai/Datus-agent#1426](https://github.com/Datus-ai/Datus-agent/issues/1426))

## Tests

```bash
.venv/bin/python -m pytest     # green incl. one strict-xfail upstream sentinel
.venv/bin/python -m ruff check .
```

## Dependencies & licensing

Compile engine: **our own sqlglot renderer** (`ariadne/render.py`, ADR-0008) over
`sqlglot` (MIT) — the runtime is **AGPL-free**: `datus-semantic-osi` and its
AGPL-3.0 transitive dependency `datus-metricflow` were removed from the
dependencies (spec rev 7; the datus engine remains documented in
[datus-spike.md](docs/research/datus-spike.md) as the superseded mechanism and in
[ADR-0008](docs/adr/0008-own-sqlglot-compiler-agpl-exit.md)). Remaining runtime
dependencies: `duckdb`, `mcp` (pinned `<2` — 2.x renames the FastMCP tool API),
`sqlglot`, `openai`, `pyyaml`. The proprietary `dosi-engine` (Elastic-2.0) was
evaluated and **not** adopted — see the engine correction in the
[research study](docs/research/agentic-semantic-layer-architecture.md).
