# Ariadne

Governed metrics for autonomous agents. An authoring agent profiles a database, combines
the profile with human seed notes, and drafts a Context Layer (OKF Markdown) plus a
Semantic Layer (OSI YAML) into `staging/`. A human promotes them into the served layers;
agents then query governed metrics over MCP — Datus compiles the OSI to SQL, a
facade-owned DuckDB connection executes it, and `get_metric` never accepts raw SQL.
Spec: [docs/specs/mvp-vertical-slice.md](docs/specs/mvp-vertical-slice.md) · research:
[docs/research/](docs/research/) (Datus integration evidence in
[datus-spike.md](docs/research/datus-spike.md)).

## Setup

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e .
```

Live authoring credentials are read from `$ARIADNE_ENV` (default
`/home/volker/coding/ariadne/.env`, never committed): `OPENAI_API_KEY`,
`OPENAI_BASE_URL`, `OPENAI_MODEL`.

## Demo

Scripted end-to-end (CI-friendly, auto-promotes):

```bash
scripts/demo.sh --yes
```

seed → author (live LLM) → promotion gate → facade + scripted MCP client; prints metric
rows and the compiled SQL. Without `--yes` the script pauses for human promotion.

## Serving to an MCP-capable agent

```bash
.venv/bin/python -m ariadne.serve --db data/demo.db \
    --semantic semantic_layer --context context_layer
```

stdio transport; exactly three tools:

- `list_metrics()` — served governed metrics with descriptions
- `search_context(query)` — ranked matches over the Context Layer (OKF)
- `get_metric(name, dimensions, range)` — rows plus the compiled SQL; unknown metric
  errors list the available metrics; `range` is `{"start", "end"}` on the primary date
  dimension

`scripts/mcp_client.py` runs the same calls headlessly and asserts the metric rows
against `tests/fixtures/expected_metrics.json`.

## Tests

```bash
.venv/bin/python -m pytest
```
