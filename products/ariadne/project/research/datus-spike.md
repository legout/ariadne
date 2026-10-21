# Probe Verdict: Datus Feasibility Spike (T0)

| | |
| :--- | :--- |
| **Type** | Research — probe report (evidence per `project/agents/artifacts.md`) |
| **Status** | Verdict: **PASS — proceed with Datus for #4/#5** |
| **Date** | 2026-09-14 |
| **Ticket** | [#1](https://github.com/legout/ariadne/issues) — T0 Datus spike, gate for T3 (#4) / T4 (#5) |
| **Question** | Can Datus (a) install in a clean venv, (b) compile the research doc's `orders.yml`, (c) execute the result on DuckDB against SQLite, (d) be called from Python? |
| **Evidence base** | [agentic-semantic-layer-architecture.md](agentic-semantic-layer-architecture.md) §5B (orders.yml), §3/§9–§11 (tool index, escape hatch, version pins); [mvp-vertical-slice.md](../specs/mvp-vertical-slice.md) §4, §10 Phase 0 |
| **Probe environment** | Ubuntu arm64; uv venv; CPython 3.12.8; probe scratch kept disposable in `/tmp/datus-spike/` (never committed) |

---

## 1. Verdict summary

| Point | Result | One-line evidence |
| :--- | :--- | :--- |
| (a) Clean-venv install | **PASS** | `uv pip install 'datus-semantic-osi[metricflow]' duckdb` — resolves and imports cleanly; full `datus-agent` install also clean; CLI `datus --version` → `Datus CLI 0.4.1` |
| (b) Compiles research S5B `orders.yml` | **PASS** | Adapted to OSI-core (`version: 0.2.0.dev0`); `validate_semantic()` → `valid=True` (1 advisory warning); `query_metrics(dry_run=True)` returns governed SQL (verbatim in §3) |
| (c) Executes on DuckDB over SQLite | **PASS** | Compiled SQL executed on a DuckDB 1.5.x connection with `ATTACH '<demo.db>' AS demo (TYPE SQLITE, READ_ONLY)` (sqlite_scanner); rows match the hand-computed fixture exactly (§4) |
| (d) Callable from Python | **PASS** | `DatusOSIAdapter(DatusOSIConfig(semantic_models_path=…))` + async `validate_semantic` / `list_metrics` / `query_metrics`; works **without** `datus-agent` installed (§5) |

**Mechanism decision for T3/T4 (the deliverable):** use **Python imports of `datus_semantic_osi`** (compile-only) and execute the compiled SQL on **our own facade-owned DuckDB connection**. Datus's own live-execution backend cannot attach SQLite (§6), and spec §4/§5/§7 already assign execution to the facade-owned DuckDB connection. The facade hides the split; `get_metric` still returns rows plus compiled SQL (provenance). Escape hatch (Cube) not needed.

---

## 2. (a) Install — exact packages, commands, versions

The name `datus` on PyPI is unclaimed. The stack is split across distributions (all require `python >= 3.12`; `datus-metricflow` requires `>=3.12,<3.13`):

| Distribution | Version (probed) | Role | License |
| :--- | :--- | :--- | :--- |
| `datus-semantic-osi` | 0.1.7 | OSI authoring → Semantic IR → SQL lowering; `DatusOSIAdapter` | Apache-2.0 (per repo) |
| `datus-semantic-metricflow` | 0.2.14 | MetricFlow execution backend used by the OSI adapter | Apache-2.0 (per repo) |
| `datus-metricflow` | 0.2.8 | Vendored MetricFlow engine (ships `metricflow` module, duckdb SQL client) | **AGPL-3.0-or-later** |
| `datus-semantic-core` | 0.2.4 | `BaseSemanticAdapter` interfaces | Apache-2.0 (per repo) |
| `duckdb` | 1.5.5 (lean venv) / 1.5.2 (full-agent venv) | execution engine | MIT |
| `duckdb-engine` | 0.17.0 | SQLAlchemy dialect for duckdb | MIT |
| `sqlglot` | 30.18.0 | expression parse/emit | MIT |
| `datus-agent` | 0.4.1 | full agent CLI (`datus`, `datus-mcp`, …) — **not needed** for the facade path | Apache-2.0 |

Clean-venv commands (both verified):

```bash
# Lean install — what ariadne (#4/#5) should use:
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python 'datus-semantic-osi[metricflow]' duckdb

# Full agent (verified too, but pulls litellm, lancedb, tantivy, anthropic, PyGithub, …):
uv pip install --python .venv/bin/python datus-agent
```

Notes:

- OSI authoring files must conform to the **OSI core schema pinned by the package**: `version: 0.2.0.dev0` (`datus_semantic_osi.profile.CORE_SCHEMA_VERSION`). This satisfies research §11's "pin OSI to a spec version" — record it in `pyproject.toml`/docs when #4 lands.
- The legacy *flat* S5B sketch (top-level `datasets:`/`measures:`/`joins:`) is **rejected** by `load_osi_path` unless `allow_legacy_profile=True` (migration-only). The research example must be adapted to OSI core — see §3.
- `dosi-engine` (proprietary Rust DOSI engine, Elastic-2.0, binaries-only via `datus-ai/dosi-dist`) was **not needed**; the open `datus-semantic-osi` compile path suffices.
- **License flag for the owner (no action for MVP):** the execution path drags in AGPL-3.0 `datus-metricflow`. Fine for this private PoC; revisit before any external distribution. `datus-semantic-osi` itself does not require it at import time, but `query_metrics` needs the metricflow backend to render SQL.

## 3. (b) Compile — S5B `orders.yml` adapted + compiled SQL

### 3.1 Required adaptations (all mechanical)

S5B sketch → OSI core `0.2.0.dev0` + DuckDB-over-SQLite binding:

| Research S5B | Installed compiler (0.1.7) accepts |
| :--- | :--- |
| `source: iceberg_catalog.finance.orders` | `source: demo.main.orders` (string three-part name; `SELECT`/`WITH`-prefixed strings become query sources) |
| `primary_key: order_id` | `primary_key: [order_id]` (list form) |
| `dimensions[].sql` | `fields[].expression.dialects[]` blocks; a `dimension:` block opts a field into grouping; `dimension: {is_time: true}` marks the primary time dimension (replaces `order_timestamp::DATE`) |
| `measures[].filters` (exclude CANCELLED/RETURNED) | `CASE WHEN` inside the aggregate — exactly what `datus.resources.skills.dosi-semantic-authoring` prescribes |
| `gross_margin: (gross_revenue - cogs) / NULLIF(gross_revenue, 0)` referencing sibling measures | same formula + DATUS `custom_extensions` hint `{"metric_kind":"derived","inputs":["gross_revenue","cogs"]}` (unknown hint keys are rejected — e.g. a `"v"` version key errors) |

Metric `expression` dialect strings: schema suggests `ANSI_SQL`/`SNOWFLAKE`/… but accepts any string; the parser prefers an `ANSI_SQL` entry, then the first entry. Expressions are parsed with the **datasource's** sqlglot dialect (`resolve_sqlglot_dialect("duckdb")` → `duckdb`).

### 3.2 Validation result

```text
validate_semantic: valid=True issues=1
issue: severity='warning'
  "[semantic_model=orders] Metric `gross_revenue` aggregates column `status`
   which dataset `orders` also models as a dimension; grouping by a measure's
   raw value is usually unintended. …"
```

Expected and advisory-only: our intended pattern (gotcha encoded as `CASE WHEN status NOT IN …` while `status` stays a groupable dimension) triggers this authoring-quality lint. `valid=True` stands. **T3 note:** the validate loop should treat severity `warning` as pass-through and only `error` as compile failure.

### 3.3 Compiled SQL (verbatim, `query_metrics(metrics=["gross_revenue","gross_margin"], dimensions=["region"], dry_run=True)`)

```sql
SELECT
  COALESCE(subq_4.region, subq_10.region) AS region
  , MAX(subq_4.gross_revenue) AS gross_revenue
  , MAX(subq_10.gross_margin) AS gross_margin
FROM (
  SELECT
    region
    , SUM(orders_case_when_not_status_in_cancelled_returned_then_amount_else_0_end_sum) AS gross_revenue
  FROM (
    SELECT
      region_code AS region
      , CASE WHEN NOT status IN ('CANCELLED', 'RETURNED') THEN amount ELSE 0 END AS orders_case_when_not_status_in_cancelled_returned_then_amount_else_0_end_sum
    FROM demo.main.orders orders_src_2
  ) subq_2
  GROUP BY
    region
) subq_4
FULL OUTER JOIN (
  SELECT
    region
    , (gross_revenue - cogs) / NULLIF(gross_revenue, 0) AS gross_margin
  FROM (
    SELECT
      region
      , SUM(orders_case_when_not_status_in_cancelled_returned_then_amount_else_0_end_sum) AS gross_revenue
      , SUM(orders_product_cost_sum) AS cogs
    FROM (
      SELECT
        region_code AS region
        , CASE WHEN NOT status IN ('CANCELLED', 'RETURNED') THEN amount ELSE 0 END AS orders_case_when_not_status_in_cancelled_returned_then_amount_else_0_end_sum
        , product_cost AS orders_product_cost_sum
      FROM demo.main.orders orders_src_2
    ) subq_7
    GROUP BY
      region
  ) subq_9
) subq_10
ON
  subq_4.region = subq_10.region
GROUP BY
  COALESCE(subq_4.region, subq_10.region)
```

The derived metric lowers to a second aggregate subquery joined per dimension (FULL OUTER + COALESCE), and to a CROSS JOIN when no dimensions are requested. Dialect-correct for DuckDB; S5B's `NOT IN` filter is provably present.

### 3.4 Compile determinism (plan's named risk — resolved with a nuance)

Two compile passes (fresh `DatusOSIAdapter` each) produce SQL that is **not byte-identical but structurally identical**: only the auto-generated alias suffixes (`subq_N`, `orders_src_N`) differ — they come from a process-local counter that advances across compiles. After normalizing those aliases, passes are byte-identical (asserted in the probe). Consequences:

- Acceptance tests that assert **rows/values** are safe.
- Anything that diffs compiled SQL text (e.g. an authoring-loop "did the model change?" check) must normalize `subq_\d+`/`orders_src_\d+` first, or compare result values instead.
- Returning compiled SQL as provenance is fine; its alias numbering is not a stable identifier.

## 4. (c) Execute on DuckDB against SQLite (sqlite_scanner)

Probe data: deterministic SQLite `demo.db` — `orders(order_id, order_timestamp, status, region_code, amount, product_cost, customer_id)`, `customers(id, customer_name)`, 8 orders across `COMPLETED`/`CANCELLED`/`RETURNED` and `EMEA`/`NA`/`APAC`.

Execution path (matches spec §4: "Datus compiles OSI → SQL → DuckDB executes"):

```python
con = duckdb.connect("warehouse.duckdb")
con.execute("ATTACH 'demo.db' AS demo (TYPE SQLITE, READ_ONLY)")   # sqlite_scanner
rows = con.execute(compiled_sql).fetchall()
```

Executed governed query — `gross_revenue, gross_margin by region`:

```text
columns: ['region', 'gross_revenue', 'gross_margin']
row: ('NA',   250.0, 0.4)
row: ('APAC', 390.0, 0.5769230769230769)
row: ('EMEA', 180.0, 0.2777777777777778)
totals (no dimensions): {'gross_revenue': 820.0, 'cogs': 445.0, 'gross_margin': 0.4573170731707317}
```

Cross-checked against the hand-computed fixture — including the deliberately subtle S5B semantics that the status filter guards **`gross_revenue` only** while `cogs = SUM(product_cost)` counts every order (so the cancelled EMEA order's 60.0 cost stays in cogs: `(180 − 130) / 180 = 0.2777…`). The compiler encodes the model exactly as authored, gotcha included.

Range contract for `get_metric` (§4 `range`): `query_metrics(..., time_start="2024-06-01")` applies the filter on the primary time dimension (the `is_time` field) and returns the correct window: `{'EMEA': 80.0, 'NA': 50.0, 'APAC': 90.0}` — only June–August orders.

## 5. (d) Callable from Python — the mechanism decision

Working mechanism (**chosen for #4/#5**): Python import, no subprocess, no `datus-agent` required.

```python
from datus_semantic_osi.adapter import DatusOSIAdapter
from datus_semantic_osi.config import DatusOSIConfig

adapter = DatusOSIAdapter(DatusOSIConfig(semantic_models_path="semantic_layer/models/"))

await adapter.validate_semantic()                    # T3 validate loop (valid: bool + issues)
await adapter.list_metrics()                         # T4 list_metrics() discovery
await adapter.list_semantic_models()                 # dimension inventory
await adapter.query_metrics(                         # T4 get_metric():
    metrics=["gross_margin"], dimensions=["region"],
    time_start="2026-01-01", time_end="2026-04-01",
    dry_run=True,                                    # -> QueryResult.metadata["sql"]
)
```

Rejected alternatives, for the record:

- **CLI subprocess** — `datus` 0.4.1 exists and runs, but it is the *LLM agent REPL* (needs agent.yml/OpenAI config); not a deterministic compile service. Wrong tool.
- **`datus-mcp` / adapter live execution** — the MCP entry point and the live `query_metrics(dry_run=False)` path require `db_config`; with `type: duckdb` Datus opens its own SQLAlchemy connection, and `DuckDbSqlClient` (metricflow/sql_clients/duckdb.py) has **no attach facility**, so it cannot see our SQLite file. Also unnecessary: spec §7 already assigns one DuckDB connection to the facade process.

## 6. Environment facts and gotchas (feed #4/#5)

1. **Python floor is 3.12** (not 3.11 as the plan's runtime assumption says): `datus-semantic-*` require `>=3.12`; `datus-metricflow` pins `<3.13,>=3.12`. Use Python 3.12 exactly.
2. **DuckDB does not persist non-DuckDB attaches**: `ATTACH … (TYPE SQLITE)` is in-connection only (verified on 1.5.2/1.5.5). The facade must ATTACH at startup on its long-lived connection (spec §7 topology already assumes this).
3. **Datus live execution can't attach SQLite** (§5). Compile with the adapter, execute on the facade's connection.
4. **Compile determinism** is structural, not textual (§3.4). Normalize aliases before any SQL-text comparison.
5. **Authoring-quality warning** fires for `CASE WHEN <dimension-column> …` inside an aggregate (§3.2) — the intended gotcha pattern. Only `severity='error'` should fail the T3 loop.
6. **DATUS extension hint keys are strictly validated**; `{"metric_kind": …, "inputs": …}` are supported on metrics, a stray `"v"` key raises `OSIValidationError`.
7. **`dry_run=True` works with no `db_config`** — compile-only mode needs no warehouse credentials; nothing in the spike required credentials or paid access.
8. Pin for #4/#5: `datus-semantic-osi==0.1.7`, `datus-semantic-metricflow==0.2.14`, `datus-metricflow==0.2.8`, `duckdb>=1.5` (1.5.2 and 1.5.5 both probed green), Python `3.12.*`. Upgrade deliberately per research §11.
9. **AGPL note** (repeat of §2): `datus-metricflow` is AGPL-3.0-or-later; acceptable for this private PoC, revisit before external distribution.

## 7. Probe reproduction sketch

Disposable probe (never committed): `/tmp/datus-spike/{venv,venv-min,probe}` —
`probe/seed_sqlite.py` (deterministic seed), `probe/models/orders.yml` (adapted OSI-core model), `probe/probe.py` (steps: seed+attach → adapter → validate → dry-run SQL → execute on attached connection → fixture asserts → range query → determinism assert). Final run: `PROBE OK` in both venvs; full logs `probe/probe_run.log`, `probe/probe_run_min.log`. The compiled SQL, results, and warnings above are quoted from those logs verbatim.

**Gate outcome:** #4 (author + validate) and #5 (MCP facade) may build on `datus-semantic-osi` per §5. Escape hatch (Cube, research §9/§11) not triggered.

## 8. Correction (2026-09-17, spec rev 7 / ADR-0008)

**Mechanism superseded.** The §5 gate outcome above (build #4/#5 on
`datus-semantic-osi`) held only until the AGPL exit: the datus compile path was
replaced by our own sqlglot compiler, `ariadne/render.py` (ADR-0008, spec rev 7).
§6 fact 6 survives in-repo — the DATUS custom_extensions hint is strictly
validated (`{metric_kind, inputs}` keys; a stray key fails the compile) by the
new renderer, pinning the contract the broken-model tests rely on. Everything
else in this document is mechanism history: the envelope shape (§3.1), the
lowering gotchas (§6, incl. qualifier-stripping, which `render()` reproduces),
and the AGPL note in fact 9 (now moot — the runtime no longer imports any datus
package).
