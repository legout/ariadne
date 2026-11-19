# Specification 0037: Simple Ariadne — one CLI, one approval, automatic drafts, Ossie 0.3

**Status:** owner-approved revision 2, 2026-11-19 ("ja"). Approval authorizes preparing the `lock_down` spike; not implementation, commits, integration or publication. Revision 1 was owner-approved on
2026-11-19 ("Ja. Freigegeben"); that approval authorized writing the research note
and sub-spec D with its plan, not implementation, commits, integration or
publication. Revision 2 adds ad-hoc SQL, the run log, `lock_down` and saved answer
examples, from the owner's 2026-11-19 answers: "Ja, ersetzt define_metric", "Warnen,
nicht sperren", "Auf Zuruf, sofort nutzbar" and "Standard an, ohne Ergebniszeilen".


**Owner decisions (Pi conversation 2026-11-18):** Ariadne becomes markedly simpler
and faster to set up and use; reuse NVIDIA auto-ontology and Apache Ossie libraries
instead of rebuilding them unless hard reasons exist; one `ariadne <subcommand>` CLI;
simplified approval ("interaktive Bestätigung"); automatic authoring (built-in
deterministic draft with optional LLM, and/or auto-ontology as engine); knowledge-only
changes go live immediately, marked as unreviewed; Python `>=3.12`; upgrade to the latest
Ossie spec, breaking metric identities with a one-time migration; umbrella plus four
sub-specifications; test-diet and deslop first; older artifacts are marked superseded
rather than rewritten.

Evidence: [NVIDIA auto-ontology review](../research/2026-11-18-auto-ontology-comparison.md);
[duckdb-analytics-agent review](../research/2026-11-19-duckdb-analytics-agent.md).

## 1. Goal and target journey

From an empty directory to a governed answer in four commands, with no IDs, revisions,
digests, namespaces or hand-written selector files:

```text
ariadne init                          # creates Git repo, namespace, private profile, selector
ariadne add s3://bucket/sales/orders  # source, file, database or document → automatic draft
ariadne preview "revenue by month"    # query the draft (governed: false)
ariadne approve                       # one human confirmation → served (governed: true)
```

Questions without an approved metric still get an answer:

```text
ariadne context "churn by cohort"     # context pack: datasets, columns, joins, rules, examples
ariadne sql "SELECT …"                # guarded ad-hoc SQL → governed: false + warnings/caveats
ariadne save-example                  # optional: question + SQL as a Lumio Answer Example
ariadne promote                       # optional: SQL → Ossie metric draft → preview → approve
```

## 2. Non-goals

- No hosted service, web UI or Postgres requirement for the local route.
- No in-process embedding of the `auto-ontology-server` package (Postgres-bound, Python
  `<3.14`, ~40 heavy dependencies, unstable internal API). It is integrated only as an
  external service through Ossie YAML.
- No relational or wide-table Ossie query interfaces (Layers 2 and 3), and no Ossie
  ontology documents. These are recorded as later candidates.
- No backward compatibility shims, aliases or deprecated entry points.
- No documentation rewrite inside the sub-specs. The documentation is rewritten once,
  after sub-specs A–C land (sub-spec E, which is shaped later).

## 3. Sub-specifications and order

| # | Sub-spec | Owns | Depends on |
|---|---|---|---|
| D | 0038 Lean baseline: test-diet, then deslop | Removing tests that detect no reachable production failure, plus dead or legacy code; supersedes the proposed plan 0036 | — |
| A | 0039 Python `>=3.12`, DuckDB `>=2.0` and Ossie 0.3 | Interpreter floor, DuckDB 2 port, Ossie loader/compiler, identity migration | D |
| B | 0040 One CLI and simplified governance | `ariadne` subcommands, active draft, single approval, preview queries, change tiers | A |
| C | 0041 Automatic authoring | Deterministic draft, optional LLM enrichment, auto-ontology and Ossie imports, Answer Examples, `promote`, run-log backlog | A (B for the `add` entry point) |

Each sub-spec gets its own implementation plan and executes sequentially in the order D → A → B → C.
A throwaway **`lock_down` spike** runs before B is shaped. It probes DuckDB
`enable_external_access=false` + `allowed_directories` + `lock_configuration=true`
against the trusted-catalog views, Delta/Iceberg/DuckLake and S3 storage profiles
Ariadne uses. Its verdict is filed under `project/research/`.
**Spike result (2026-11-19):** [probe report](../research/2026-11-19-lockdown-spike.md).
`lock_down` works with every source type but is not sufficient on its own. Sub-spec B
must add a statement guard and a parse-tree guard (no table functions; only
registered relations).

## 4. Sub-spec summaries (binding scope; detail belongs to the sub-specs)

### D — Lean baseline
Run `test-diet` over the whole suite, then `deslop` over `ariadne-data`, `lumio-wiki`
and `lumio-workspace`. Code and tests that only serve surfaces this umbrella removes
(the separate `ariadne-*` executables, the preview/confirm double admission, manual
revision plumbing) are not modernized; they are deleted in B. Behavior that stays
(compiler, grain/fan-out guard, source containment, execution attestation, Lumio
admission) must keep at least one test that proves real behavior.

### A — Python `>=3.12` and Ossie 0.3
- All four packages declare `requires-python = ">=3.12"`. CI runs 3.12, 3.13 and 3.14.
  The 3.14-only unparenthesized `except A, B:` syntax (7 sites) is fixed.
- **DuckDB `>=2.0`** (owner, 2026-11-19: "wir wollen definitiv duckdb>=2.0 nutzen"):
  - Replace the current `duckdb>=1.0,<2` pin.
  - Port the bounded reads that DuckDB 2.0 removed (relation `fetchmany`/`fetchone`;
    `execution.py` and `contract_inspection.py` among others).
  - Re-run the [lock_down probe](../research/2026-11-19-lockdown-spike.md) gap classes
    G1–G7 and the parse-tree guard's node types under 2.0.
  - Re-verify the delta, iceberg, ducklake, postgres, sqlite and httpfs extensions.
  - Lumio packages that use DuckDB follow.
- Pin Ossie `0.3.0.dev0` to an exact `apache/ossie` commit. Ship its
  `ossie-schema.json` and validate with the existing `jsonschema` dependency. Use the
  `apache-ossie` Pydantic package only if it removes code (decided in A).
- Required changes:
  - One model per document at the root (no `semantic_model` array).
  - `expression.sql` (`OSSIE_SQL_2026`) is primary; `dialects` is optional.
  - Metrics, keys and relationship columns resolve to fields; `source.column` names
    source columns.
  - Dataset-scoped metrics, plus model-scoped metrics with `dataset.field` and
    `AGG(dataset.metric)`.
  - `nonportable_extensions` (object `data`) replaces `custom_extensions`.
  - True division and half-away-from-zero `ROUND`.
  - `ai_context` is preserved as guidance only.
- Metric identity becomes `model::metric` for model-scoped metrics and
  `model::dataset.metric` for dataset-scoped metrics. `ariadne migrate` rewrites a
  project once: semantic models, Policy Bindings, Lumio `ariadne-context` references
  and Answer Examples. Repository fixtures and examples are migrated by the same command.

### B — One CLI and simplified governance
- One executable: `ariadne init | add | draft | preview | diff | approve | reject |
  review | revert | status | query | metrics | search | serve | import | skill | migrate`.
  All other `ariadne-*` executables are removed.
- `init` creates or uses Git, generates a UUID namespace, writes the private profile to
  `~/.config/ariadne/<project>.json` and writes the integration selector. Missing Git
  identity falls back to a project-local identity after one prompt.
- **One active draft per project.** The CLI tracks the draft, its revision and its
  digests internally. A stale draft (a concurrent change) is refused with a concrete
  rebase hint.
- **Calculation changes** (tier C: sources, semantic models, joins, metrics, Policies,
  contracts and bindings) are served only after `ariadne approve`. `approve` shows the
  complete summary and validation result, then requires interactive confirmation on a
  TTY. It records the Git identity and the approved digest in one step. MCP exposes no
  approve operation, and the packaged skill forbids agents from running it. A source
  added by the operator through `ariadne add` is approved by the same `approve`; no
  separate source-approval step exists.
- **Knowledge changes** (tier K: Lumio pages, descriptions and synonyms not bound as a
  required Policy or computation) are served right after successful validation.
  Answers that use an unreviewed tier-K page carry `unreviewed: [page ids]` until
  `ariadne review` countersigns them. `ariadne revert <page>` restores the last
  reviewed state.
- **Preview queries:** `ariadne preview` and MCP `query(draft=true)` compile the active
  draft with the same compiler and guards. They return `governed: false` plus the draft
  revision and are never stored as Answer Examples.
- **Ad-hoc SQL** replaces `define_metric` and `query_records` (ADR-0005 and ADR-0019
  are superseded). The CLI `ariadne sql` and the MCP tool `sql` run one agent-written
  `SELECT`/`EXPLAIN`:
  - Guards: approved sources only, attached read-only. Then `lock_down` (no external
    file or URL access beyond the approved data paths, locked configuration). Plus the
    single-statement check, the deadline and result caps that already exist.
  - The result always carries `governed: false`. It also carries the tables it read
    (parsed with sqlglot), their required Policies and caveats, `unreviewed` pages,
    and **warnings**.
  - Grain, fan-out and joins absent from the model are warned, never refused.
- **Context pack:** `ariadne context <question>` and the MCP tool `context` return,
  within a size budget:
  - relevant datasets and columns with descriptions and observed values;
  - relationships with their cardinality;
  - filter rules and Policies;
  - approved metrics that nearly match;
  - the most similar Answer Examples including their SQL.
- **Run log:** on by default in `.ariadne/runs.duckdb`, local and git-ignored.
  - Per call it records: operation, question (when given), SQL, tables read, outcome,
    error or refusal class, warnings, row count, duration, and the served revision.
  - **It stores no result rows.** Retention is 90 days, configurable. It can be turned
    off.
  - It is runtime state, not authored state, and never changes retrieval or models by
    itself.
- The shared workspace server adopts the same tiers and single approval. Its browser
  review stays the human confirmation channel for remote users.

### C — Automatic authoring
- `ariadne add <path|url|dsn|document>` detects the source type, for example a Delta
  table via `_delta_log/`, Parquet/CSV/JSON, Iceberg, DuckDB/SQLite/Postgres, or a
  document. It then profiles the source and writes a draft.
- **Deterministic drafter (always available, no network):**
  - Ossie datasets and fields with time roles.
  - Primary keys, and relationships whose foreign keys are data-confirmed with their
    cardinality.
  - Per-dataset metric candidates (row count, sums of numeric non-key measures).
  - An ODCS contract (types, nullability, uniqueness).
  - Lumio pages per dataset.
- **Optional LLM enrichment** through any OpenAI-compatible endpoint (including NVIDIA
  NIM): descriptions, synonyms, term names, metric proposals from Seed Notes and
  documents, and document distillation. Without a configured model, the deterministic
  draft is complete and usable.
- **auto-ontology as an optional engine:** `ariadne import auto-ontology <url|file>`
  pulls an Ossie export from a running auto-ontology server, or reads its YAML, and turns
  it into a draft. It uses the `apache-ossie-nvidia-auto-ontology` converter as an
  optional extra.
- `ariadne import ossie|dbt|cube|snowflake|databricks <file>` uses the matching Apache
  Ossie converters as optional extras.
- **Answer Examples on request:** `ariadne save-example` (MCP `save_example`) writes
  the question, intended meaning, SQL, tables read and a bounded result summary with
  its date as a Lumio page.
  - It is tier K: immediately searchable and returned by `context`, marked
    `unreviewed` until countersigned.
  - Retrieval uses Lumio search (lexical, or BM25 through `lumio-lancedb`); no
    separate JSONL or vector store.
  - Examples are method references, never cached answers.
- **`ariadne promote`** turns a saved example's or the last run's SQL into an Ossie
  metric draft (tier C) when it is a single-aggregate shape the compiler can express.
  Otherwise it reports why not.
- **Backlog from the run log:** `ariadne gaps` lists recurring ad-hoc questions,
  tables and failure classes without an approved metric, as input for drafting. It
  never acts automatically.
- Every draft, whatever its origin, passes the same validation and tier rules as B.
  Nothing generated is served as tier C without `approve`. ADR-0027 is revised:
  host agents remain supported but are no longer required for authoring.

## 5. Invariants that survive

1. Governed numbers come only from approved semantic definitions, compiled
   deterministically. Ad-hoc SQL is always labeled `governed: false`, never governed.
2. For governed queries the grain/fan-out guard, read-only execution, source
   containment and execution attestation are unchanged in strength. Ad-hoc SQL keeps
   read-only execution and source containment (strengthened by `lock_down`) and gets
   grain/fan-out as warnings.
3. Required Policies travel with every governed answer.
4. Credentials are referenced by environment-variable name only, never stored or
   shown to models.
5. Every served state is reproducible from Git plus the recorded approval.

## 6. Acceptance examples (umbrella level)

1. A fresh machine with Python 3.12 runs `pip install ariadne-data` → `ariadne init` →
   `ariadne add data/orders.parquet` → `ariadne preview "row count"` → `ariadne approve`
   (confirmed) → `ariadne query <metric>`. The query returns `governed: true`. No step
   asks for an ID, revision, digest, namespace or YAML file.
2. The same flow with a local Delta table under an S3-compatible path declared through
   the storage profile produces a draft with datasets, fields and a contract, without
   any LLM configured.
3. `ariadne approve` without a TTY refuses. The MCP server exposes no approve tool.
4. Editing a Lumio guide page is served immediately. A governed answer that uses it lists
   the page under `unreviewed` until `ariadne review` runs.
5. Editing a metric expression is visible to `ariadne preview` with `governed: false`,
   and `ariadne query` keeps serving the old definition until `approve`.
6. `ariadne migrate` on the repository's examples produces valid Ossie `0.3.0.dev0`
   documents that pass the pinned schema. Their numerical golden results are unchanged,
   or changed only where true division or `ROUND` semantics apply and the change is
   independently explained.
7. `ariadne import auto-ontology` on an exported Wide World Importers model yields a
   draft that validates; `approve` then serves at least one metric.
8. The test suite after D contains no test without a named reachable failure scenario.
9. `ariadne sql "SELECT * FROM read_csv('~/.env')"` and any write, `ATTACH`, `SET`,
   `INSTALL` or second statement are refused. A window-function cohort query over
   approved sources runs and returns `governed: false` with the tables it read.
10. An ad-hoc join that duplicates a fact across a 1:N relationship returns its
    result plus a fan-out warning naming the relationship.
11. `ariadne save-example` followed by `ariadne context` with a paraphrased question
    returns that example with its SQL and `unreviewed: true`.
12. After ad-hoc runs, `.ariadne/runs.duckdb` holds SQL, tables and outcomes but no
    result values. `ariadne gaps` lists the repeated question.

## 7. Artifact reconciliation (project/)

- **New ADRs (proposed within sub-specs):**
  - Single interactive approval and change tiers (B; supersedes the gate structure of
    ADR-0010, ADR-0016, ADR-0024 and ADR-0026 and the shared ADR-0029 where they
    conflict).
  - Built-in drafting with optional LLM (C; revises ADR-0013 and ADR-0027).
  - Ossie 0.3 as the semantic format (A; amends ADR-0008, which also loses its 3.14
    amendment).
  - auto-ontology integrated only as an external service (C).
  - Guarded ad-hoc SQL with warnings, replacing structured ad-hoc metrics and record
    queries (B; supersedes ADR-0005 and ADR-0019, amends ADR-0015 for on-request
    tier-K examples).
  - Run log as local runtime state without result rows (B).
  - Lumio ADR-0030 is amended for the new metric identities (A).
- **Superseded markers:** every older spec, plan and ADR whose behavior conflicts gets a
  header `Superseded by spec 0037/<sub-spec>` with a one-line scope note; its content
  stays as history. Plan 0036 is superseded by sub-spec D. The list of affected files is
  produced in each sub-spec, not guessed here.
- **CONTEXT.md** (Ariadne, and Lumio where shared):
  - Redefine Source Approval, Git Review Admission, Authoring Proposal, Candidate
    Revision and Authoring Agent.
  - Remove Staging and Promotion.
  - Add Draft, Preview Query, Knowledge Change, Calculation Change, Unreviewed Knowledge,
    Ossie Model, Ad-hoc Query, Context Pack and Run Log.
  - Replace Ad-hoc Metric, Ad-hoc Record Query and Proposal with Ad-hoc Query.

## 8. Open decisions (owned by sub-specs)

- A: whether to use the `apache-ossie` Pydantic models or keep plain dict plus JSON Schema.
- B: Git identity fallback wording; whether `review` can countersign selected pages or
  only all unreviewed pages.
- C: the default metric-candidate heuristics; whether auto-ontology export is pulled over
  REST or only file-imported first; which SQL shapes `promote` accepts.
- B: the context-pack size budget and ranking; the exact warning classes.
