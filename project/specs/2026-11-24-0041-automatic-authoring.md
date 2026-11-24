# Specification 0041: Automatic authoring — drafts, imports, Answer Examples, `promote`, `gaps` (C)

**Status:** proposed, revision 2, 2026-11-24. The owner selected the four review
resolutions below; the complete written revision is not approved. The combined plan
requires approved B3 and C specifications; execution, integration and publication
remain separately gated. This is sub-spec C of the
[approved umbrella spec 0037 r2](2026-11-18-0037-simple-ariadne.md) and builds on the
[approved spec 0040 r3](2026-11-22-0040-one-cli-simple-governance.md) (B1 in review; B2 is
planned next; B3 lands in the same candidate as C).

**Owner decisions (Pi conversation 2026-11-24):**

- **Metric candidates:** conservative, as in 0037 §4 C — row count and sums of numeric
  non-key measures. No averages, ratios or time-bucketed variants are generated.
- **auto-ontology:** file import only in C. A REST pull from a running server is a later
  addition ("Nur Datei-Import").
- **`promote` and joins:** joined SQL is accepted ("Mit Joins"). In Ariadne a metric is
  strictly a single-dataset expression (spec 0039 §5.3; `refuse_relations`), and joins
  exist only in the planner along declared many-to-one/one-to-one relationships. So
  `promote` **decomposes** a joined query: one measure on exactly one fact dataset, and
  dimensions that are reachable through declared relationships. It never teaches the
  compiler joins (§4.2).
- **LLM enrichment:** descriptions, synonyms, term names and metric proposals from Seed
  Notes and documents. Document distillation stays with Lumio's native intake.
- **Order against B3:** B3 lands **with** C ("B3 mit C laden"). Answer Examples and
  added documents are tier K again, as 0037 §4 C states; `review`/`revert` and the
  unreviewed marker come from the B3 spec.
- **One candidate.** Drafting/imports, Examples, `promote` and `gaps` land in one
  candidate together with B3, after B2.

**Review resolutions (owner, Pi conversation 2026-11-24):** preview may use exact
already-granted identities before calculation approval; `promote` refuses shapes that
the existing planner cannot reproduce; outbound enrichment uses an explicit operator
allowlist and omits exact numeric extrema; Answer Example SQL in `context` is opt-in.

**Evidence:**

- [auto-ontology comparison](../research/2026-11-18-auto-ontology-comparison.md):
  `apache-ossie-nvidia-auto-ontology` depends only on PyYAML and sqlglot and exposes
  `convert_auto_ontology_to_ossie`; sibling converters exist for dbt, Cube, Snowflake and
  Databricks.
- Landed spec 0039 (`970b9fa`): Ossie `0.3.0.dev0` documents, strict name resolution,
  dataset-scoped and model-scoped metrics.
- Landed spec 0035 C2–C4: native Dataset/Table pages, native document intake and
  Answer Examples as Lumio knowledge (`answer_examples.py`, amended ADR-0015).
- The existing profiler (`profiler.py`): SUMMARIZE statistics, primary-key and
  foreign-key candidates with match ratio.
- The existing typed edit kinds (`authoring_edits.py`): `model`, `graph`, `page`,
  `seed_notes`, `contract`, `contract_bindings`, plus the source edit of B1.

## 1. Goal

From a granted source to a served metric without hand-written YAML:

```text
ariadne init
ariadne add data/retail.duckdb --name retail  # B1: declares the source, no reads
ariadne approve                       # B1: sources-only approval (TTY)
ariadne draft                         # C: deterministic draft from the granted sources
ariadne validate                      # B1
ariadne preview retail::orders.sum_amount  # B1: governed:false
ariadne approve                       # B1: calculation approval
ariadne query retail::orders.sum_amount    # governed:true
```

And from a question that has no metric yet back into one:

```text
ariadne sql "SELECT …"                # B2: governed:false + warnings
ariadne save-example                  # C: question + SQL as a Lumio Answer Example
ariadne promote --example <id> --name …   # C: SQL → metric draft (tier C)
ariadne gaps                          # C: recurring normalized SQL shapes
```

## 2. Non-goals

- **No embedding of `auto-ontology-server`** (umbrella §2). It is an external service
  that exchanges Ossie YAML.
- **No new join semantics, no relaxation of the compiler, the grain guard or validation.**
  Everything C generates passes the same checks as a hand-written draft.
- **No approval, source grant or mapping confirmation by any generated artifact or
  model** (0040 §3.5).
- **No tier-K mechanics in this spec.** Tier K, `review`/`revert` and the unreviewed
  marker are the B3 spec's. B3 lands in the same candidate as C (owner decision
  2026-11-24); this spec only states what Examples and documents need from it (§3.4.7,
  §4.1).
- **No REST client, scheduler or daemon.** `import` reads files; `gaps` reads the local
  run log.
- **No Ossie Layers 2/3, ontology documents or Ossie query interfaces** (umbrella §2).
- **No documentation rewrite** (umbrella sub-spec E).

## 3. Drafting

### 3.1 Commands C adds

| Command | Meaning |
| --- | --- |
| `draft [SOURCE…] [--with-seed-notes] [--with-documents FILE…]` | §3.3–3.4: draft granted, unmodeled sources; add enrichment only within the operator's disclosure allowlist. The flags select optional text inputs, not permissions. |
| `import ossie\|dbt\|cube\|snowflake\|databricks\|auto-ontology <file> [--name N]` | §3.5: convert one file to Ossie 0.3 documents and write them as `model` edits into the active draft. |
| `save-example [--file PATH]` | §4.1: submit a consented Example; read submission from stdin when no file is supplied. MCP `save_example` keeps its name. |
| `promote (--example ID \| --last) --name N [--description D]` | §4.2: SQL → one dataset-scoped metric in the active draft. |
| `gaps [--since D] [--min-count N]` | §4.3: read-only report over the run log. |

Rules that follow from 0040 §3.1: text by default, JSON with `--json`; calculation
draft writes use the one draft slot and its compare-and-set; nothing here approves.
`promote`, `import`, `draft` and `gaps` are CLI-only. C changes `save_example` without
adding MCP tools; it uses the `context` SQL opt-in from 0040 §4.4. The packaged skill
explains operator source consent and the separate outbound allowlist.

For analytical sources, `add` declares and reads nothing, as in B1. Live source
inspection and drafting happen only after approval (0040 §3.4.2). Document intake
is the separate B3 knowledge-only route (§3.4.7).

### 3.2 What `draft` reads

1. Only sources whose identity is granted (served release bindings plus
   `source_grants.json`, 0040 §3.4.4) and that have no model document in the draft or
   the served state. A named `SOURCE` that is not granted refuses and names the pending
   approval.
2. It profiles each source on a locked authoring connection (0040 §3.4 and §5):
   SUMMARIZE per table, primary-key candidates, foreign-key candidates with match ratio,
   and the planner's relationship target audit (`relationship_target_audit`) for every
   candidate edge it intends to write. Reuse bounded inspection and authorization;
   for cross-source edges both sides must be in the exact granted selection or baseline
   and checked on the locked connection. A pending, interrupted approval is not a grant.
3. It writes one atomic edit batch to the active draft: one `model` edit per source,
   one `graph` edit when relationships cross sources, one `contract` edit and one
   native Dataset `page` edit per dataset (spec 0035 C2). With no active draft, it
   creates one under 0040 §3.3; otherwise it pins the existing generation, candidate
   revision and served base. A stale batch refuses. No edits means no draft write.
4. **The deterministic draft is reproducible.** The same profile, audit outcomes and
   authored baseline yield byte-identical edits (umbrella §5.5). LLM output is not
   reproducible and is reported separately (§3.4).
5. It never overwrites: a dataset, metric, page or contract identity that already exists
   in the effective draft or served state is skipped and listed. Respect Ossie's shared
   field/metric namespace, including collisions with fields generated in this batch.

### 3.3 Deterministic drafter (no model service required)

One model document per source (`semantic_layer/models/<source>.yml`), one dataset per
profiled table, `source:` = the qualified relation the registry exposes. Per dataset:

| Artifact | Rule |
| --- | --- |
| **Fields** | One field per source column, `expression.sql` = the column. Every column gets `dimension: {}` except those chosen as measures below. |
| **Time role** | A column of a date/timestamp type is a time candidate. Exactly one candidate declares it as the dataset's time field through the existing time-role declaration; several candidates are listed in the report and none is chosen. |
| **Primary key** | Exactly one single-column candidate with `unique_ratio == 1.0` and no nulls becomes `primary_key`. Otherwise none is written and the candidates are listed. Composite keys are not derived. |
| **Relationships** | Write an edge only for a single unambiguous target with a written primary key, a passing target audit, and exact full containment of the non-null source keys (at least one observed; no sampling or rounding). Partial matches, ambiguous targets and failed audits are reported, not written. The default is many-to-one; write `one_to_one` only with exact source-side uniqueness under the existing checks. Inside one model document, or in `graph.yml` across sources. Measured containment does not establish business meaning. |
| **Metric candidates** | `row_count` = `COUNT(*)`, and `sum_<column>` = `SUM(source.<column>)` for every numeric column that is neither a key nor a foreign-key candidate, whose name does not end in `_id`, `id`, `_key` or `key`, and that has more than two distinct values. Nothing else: no averages, ratios, distinct counts or time buckets. |
| **Descriptions** | Generated from statistics only: `Sum of <column> over <dataset>; <n> nulls excluded.` No business meaning is invented. |
| **ODCS contract** | One contract per dataset from the profile: data types, nullability (from `null_count`), uniqueness (from the key candidates), through the existing contract artifact and schema. |
| **Lumio page** | One native Dataset page per dataset with the column list and the generated candidates, linked to the model identity. |

`ariadne draft` ends with the report: written datasets, metrics, relationships, contracts
and pages, plus every skipped or unconfirmed candidate with its reason. The operator then
runs `validate`, edits what the business meaning requires (by hand or through §3.4), and
approves.

### 3.4 Optional LLM enrichment

1. **Configuration and consent** live in the operator-managed private profile
   (`~/.config/ariadne/<uuid>.ariadne.json`): `llm.base_url`, `llm.model`,
   `llm.api_key_env`, and a default-empty outbound allowlist bound to that endpoint
   and model. The allowlist names exact approved analytical source identities and,
   separately, any approved Seed Notes or document versions. A source grant, CLI flag
   or endpoint configuration alone is not outbound consent; agents may not change the
   allowlist through shipped authoring interfaces. Changing destination or material
   requires a matching new entry. Without a matching source entry, draft locally.
2. **Endpoint:** any OpenAI-compatible chat-completions endpoint, including NVIDIA NIM.
   One request per allowed source, bounded in input bytes, time and tokens; at most one
   retry, no streaming. Do not follow redirects to another endpoint. Resolve the key
   from the named environment variable for authentication only; never put it in the
   request body, logs or draft.
3. **What is sent:** table and column names, types, null and distinct counts, and
   structured generated candidates, built from an explicit payload allowlist rather
   than the full profile. **Never send from the profile:** raw values, top values,
   extrema or other value-bearing statistics. Do not send credentials, the private
   profile, storage endpoints or source paths. Seed Notes (`data/seed_notes.md`) and
   converted document text are sent only if both explicitly selected for this run and
   allowlisted at the exact content version for this endpoint and source. Refuse an
   unauthorized or oversized text selection before sending any enrichment request;
   ordinary deterministic draft remains available without that selection. The operator
   reviews selected text for secrets and sensitive content before allowlisting it.
4. **What comes back:** a JSON object with, per dataset, `description`, `synonyms`,
   `label`, per field `description`, and `metric_proposals: [{name, description, sql}]`.
   Anything else in the response is ignored.
5. **Every item passes the same gates as a hand-written edit.** A metric proposal is a
   dataset-scoped expression over the dataset's own columns (spec 0039 §5.3), so it is
   parsed with the existing expression rules (`refuse_relations` included) and must be
   new in the dataset namespace. An invalid or duplicate proposal is dropped and listed.
   A response that fails to parse drops the whole enrichment for that source; the
   deterministic draft is complete without it and `draft` never fails because of the
   model.
6. **Provenance:** LLM-written descriptions, synonyms, labels and metric proposals are
   reported under their own heading in `ariadne diff` and `draft status --json`. The
   provenance lives in the draft's edit records; the Ossie document stays strictly
   schema-conformant. (The exact record field is decided in the plan against the edit
   schema; the requirement is that the reviewer can tell model text from statistics.)
   Do not retain request bodies, credentials or unaccepted model output as provenance.
7. **Documents are not distilled by the drafter.** `add notes.md` uses Lumio native
   intake and B3's knowledge-only route, not the calculation draft. Text/Markdown are
   native; PDF/DOCX use Lumio's optional document converters. An unsupported format or
   missing converter refuses with the reason. Publication after validation preserves
   scoped visibility and required original retention (spec 0035); `ariadne review`
   countersigns the unreviewed page via B3.

### 3.5 Imports

1. **Ossie converters.** `import <tool> <file>` runs the matching Apache Ossie converter
   (`apache-ossie-dbt`, `-cube`, `-snowflake`, `-databricks`, `-nvidia-auto-ontology`)
   as optional extras of `ariadne-data` (for example `ariadne-data[converters]`). None is
   a base dependency. Without the extra the command refuses and names the `pip install`.
2. **`import ossie <file>`** reads Ossie `0.3.0.dev0` documents directly, including
   native Ossie exports from auto-ontology. **`import auto-ontology <file>`** accepts
   those exports through the same direct path, or converts server-native YAML with the
   optional NVIDIA converter. It does not reconvert or repair a recognized Ossie export.
3. **One import is one transaction.** Every produced document is validated against the
   pinned schema and the strict name resolution (spec 0039 §5). If any document fails,
   nothing is written and the report names file and reason per document. Names that
   collide with existing models are refused; `--name` renames a single imported model.
4. The import never reads a data source. Validation against live data happens in
   `validate`/`approve`, as for every draft.

## 4. Answer Examples, `promote`, `gaps`

### 4.1 `save-example`

1. `ariadne save-example` and MCP `save_example` keep the C4 contract (explicit consent,
   intended meaning, bounded excerpt with date, no cached answer) with two changes:
   - new Examples record the B2 **`sql`** call (statement, tables read, result
     summary and originating served revision) rather than the legacy
     `get_metric`/`define_metric` methods; existing history is not rewritten;
   - `promote` reads the Example's SQL, so the stored SQL is the exact submitted text
     (existing `SQL_PROVENANCE_SOURCE` semantics: evidence of what was submitted).
2. The Example is authored as one native `knowledge/answer-examples/` page through the
   shared page-batch writer, as a **tier-K knowledge change**: after validation it is
   searchable within its authorized Lumio scope and marked `unreviewed: true` until
   `ariadne review` countersigns it. `context` returns Example summaries by default;
   exact SQL requires `context --include-sql` or MCP `context(include_sql=true)`.
   The flag neither widens scope nor opts into stale/rejected history. SQL does not
   participate in ranking. Without provenance, report it as not recorded on opt-in;
   do not invent SQL. Consent covers the exact submission and its intended audience,
   not just the question. Publication, scope enforcement, markers and `revert` are
   B3's; this route must not change a pinned analytics/Policy association (spec 0035).
3. An Example never opens a draft generation and never waits for `approve`.
4. Retrieval stays Lumio search (lexical; BM25 through `lumio-lancedb` when installed).
   No separate JSONL or vector store.

### 4.2 `promote`: SQL → one metric draft

**Input:** `--example ID` (SQL and intended meaning from an Example visible in the
current authorized scope) or `--last` (the latest successful `sql` record in the run
log). `--last` uses the normalized SQL with literals replaced by `?`; if the log,
record or stored SQL is absent, refuse with `sql_unavailable` rather than selecting
an older record. The same refusal applies to an Example with no SQL. `--name` is
required; `--description` overrides intended meaning; without either, use no description.

**Accepted shape** (one `SELECT`, parsed with sqlglot, never executed):

- **From:** the base relation is the fact, including for `COUNT(*)`. Each optional
  `LEFT JOIN` must follow a uniquely resolved directed many-to-one or one-to-one edge
  in the effective draft graph (served definitions are the baseline). Chains are
  allowed. Match the entire declared key and resolve each SQL alias and column to the
  same dataset and field expression the planner will use. No added `ON` predicates,
  alternate paths, or repeated dataset occurrences. Each explicit join must be
  reproduced by the planner's dimension/filter traversal; unused joins are refused.
- **Select:** one aggregate-valued expression (`COUNT`, `SUM`, `AVG`, `MIN`, `MAX`,
  optionally `FILTER` or `CASE`, or arithmetic between these), using only fact
  columns throughout. Other items are plain exposed dimensions or date truncations
  only if the current planner can reproduce the exact time field and grain.
- **Group by:** exactly those non-aggregate select items. `HAVING`, `DISTINCT` on
  the SELECT and unsupported grouping expressions are refused.
- **Where:** only conjunctions of existing planner row predicates against resolvable
  fields with supported, type-preserving values. No predicate rewriting that changes
  NULL handling or population. `ORDER BY` and `LIMIT` are intentionally omitted and
  reported as presentation differences, not equivalent row selection.
- **Literals:** preserve supported values from an Example. A redacted value in the
  metric expression or grouping must be recovered from an Example, not guessed. A
  supported outer row predicate with a redacted value can be described as requiring
  manual input, never rendered as an executable filter using a guessed value. Still
  refuse an unsupported predicate shape. Do not drop a predicate that is the only
  reason the planner traverses an explicit join; with an unknown value there, require
  the Example so that the join and predicate can be reproduced.

**Result:** one dataset-scoped Ossie metric `<model>::<dataset>.<name>` in the active
calculation draft, plus the suggested `ariadne preview <metric> --by … --filter …`.
The preview reproduces the supported aggregation, grouping and row predicates, subject
to the disclosed presentation differences and current data/Policies. With redacted
row values, label the preview **incomplete** and list the required filter inputs; do not
present it as equivalent or ready to run. `validate`, `preview` and human `approve`
remain separate; `promote` writes no relationship or calculation approval.

**Refused, each with a stable code and a hint:**

| Code | Shape | Hint |
| --- | --- | --- |
| `not_single_select` | CTE, subquery, set operation, window function, SELECT `DISTINCT`, `HAVING`, non-`SELECT` | simplify to one flat `SELECT` |
| `no_dataset` | a relation is not the `source` of exactly one dataset | run `ariadne draft` or declare the dataset |
| `undeclared_join` | join keys match no declared relationship | declare the relationship (the drafter lists candidates) |
| `join_reverses_relationship` | a declared edge points from the joined dataset toward the fact or earlier lookup, with no matching forward edge | ADR-0006: start at the dimension-traversal source grain |
| `measure_not_on_fact` | any part of the aggregate reads columns of a joined relation | model the measure at its own grain |
| `multiple_aggregates` | more than one aggregate-valued SELECT item | promote one measure per run |
| `not_representable` | `INNER JOIN`, ambiguous or extra join path, or unsupported aggregate/grouping/filter lowering | use a planner-representable shape or author the metric explicitly |
| `literal_required` | redacted value required in the expression, grouping or a filter needed to reproduce a join | use `--example` |
| `sql_unavailable` | no successful SQL text at the specified input | run a supported `sql` query or save an Example with SQL |

`promote` never writes a join, a `graph.yml` entry or a relationship. It only emits what
the existing compiler already accepts, and `validate` re-checks it.

### 4.3 `gaps`

1. Reads `.ariadne/runs.duckdb` read-only. Group successful `sql` records with stored
   text by normalized SQL, approved relation names and served revision (0040 §4.5).
   Report count, first/last seen, relations and warning classes, plus refusal classes
   with the same recorded revision and relation set. Count successful records without
   text separately. Report a missing log or disabled logging; do not create a log.
2. Report a visible served Answer Example as a **shape match** only with the same
   normalization, recorded relations and originating served revision; if that evidence
   is unavailable, report no verified match. A match does not prove business meaning,
   execution or literal equality. Report metric coverage as **unknown** in C; merely
   having metrics on the same datasets is not a match.
3. Default order: count descending; `--min-count` defaults to 2; `--since` bounds the
   window. Retention and `run_log.enabled` are B2's (0040 §4.5). Show normalized SQL
   only, never question text, literals or stored Example SQL.
4. It changes nothing: no retrieval, model or Example is changed. Suggest promotion
   by a visible matching Example ID only when its query shape is supported, with a
   reminder to check its meaning. Otherwise tell the operator to rerun the intended
   query and explicitly save it. Never suggest `--last` for an arbitrary group.

## 5. Invariants

1. **Nothing generated that affects a calculation is served without a calculation
   `approve`.** The origin — profiler, converter or model — makes no difference.
   Generated knowledge pages (Examples, added documents) follow tier K (B3): served
   after validation, marked `unreviewed`.
2. **No source is read before its grant.** `draft` profiles granted sources on locked
   authoring connections; analytical `add` reads nothing; `import` reads only the
   operator's file. Document intake is a separate permission and route.
3. **Without enrichment no model endpoint is called.** The deterministic draft is
   complete without it; profiling a granted remote source still uses its normal connection.
4. **Enrichment bodies contain only the authorized inputs in §3.4.3.** Model output
   is data: parsed, bounded and validated by the existing gates. It has no direct
   file-writing, approval, relationship or source authority.
5. **The compiler is not weakened.** `promote` emits only single-dataset expressions;
   joins remain the planner's, along declared relationships with the target audit and
   the grain guard.
6. **Examples stay method references.** Reuse performs a fresh sanctioned query; an
   Example becomes a metric only through an explicit `promote` and an `approve`.
7. **The run log stays without values.** `gaps` and `promote --last` are read-only
   consumers.
8. **A failed import, `draft` batch or `promote` writes nothing.** Each successful
   command with edits updates the draft atomically once under 0040 §3.3.
9. **Reproducibility:** deterministic draft edits and promotion results are reproducible
   for the same inputs and authored baseline. LLM enrichment is not and is labeled.

## 6. Acceptance examples

1. **Owner path.** Use one local `retail.duckdb` with `orders(id, customer_id, amount)`
   rows `(1,10,100), (2,20,50), (3,10,25), (4,30,25)` and `customers(id, region)`
   rows `(10,'West'), (20,'East'), (30,'West')`. After the source-only approval,
   `draft` writes one model with `orders.row_count`, `orders.sum_amount`,
   `customers.row_count`, and `orders.customer_id → customers.id`. `validate` passes;
   `preview` returns **200** (`100 + 50 + 25 + 25`) and `governed:false` before any
   calculation is served. After calculation approval, `query` returns **200** and
   `governed:true`. This is an unfiltered sum, not the 0039 completed-orders metric.
2. **Determinism.** Two `draft` runs from identical clean baselines with the same local
   data and no enrichment produce byte-identical edits. A repeat on the resulting
   draft makes no write. No network call is observable.
3. **Conservative candidates.** A table with `id`, `customer_id`, `quantity`,
   `is_active`, `status` yields `row_count` and `sum_quantity` only when `id` is its
   key, `customer_id` is a foreign-key candidate, `quantity` is numeric with three
   distinct values across four rows, `is_active` has two values, and `status` is text.
4. **Unconfirmed keys.** Two single-column unique candidates produce no `primary_key`;
   the report lists both. A foreign-key candidate whose target audit fails, or whose
   non-null keys only partly match a unique target, is reported but not written.
5. **No grant, no read.** A named source awaiting approval is refused and named;
   no connection is opened for it. With no grants, bare `draft` reports no work.
6. **Enrichment off.** With no `llm` configuration the draft equals the deterministic
   draft and `diff` shows no model-written items.
7. **Enrichment on.** With a local OpenAI-compatible stub, a configured endpoint and
   grant without an allowlist send no request. With exact consent, the payload includes
   permitted metadata but not a one-row column's numeric value, path, key or unselected
   notes. Changed selected document bytes refuse before a request. An invalid metric
   proposal is dropped and listed; a malformed response leaves the deterministic draft
   intact and `draft` exits 0.
8. **Import.** `ariadne import auto-ontology <export>` on an exported Wide World
   Importers model yields documents that validate; `approve` serves at least one
   metric (umbrella §6.7). A document with a `semantic_model` key fails the whole
   import and writes nothing.
9. **`save-example` + `context`.** After `sql` and explicitly consented `save-example`
   (no `approve`), an authorized caller sees the Example marked `unreviewed: true`,
   but exact SQL only with `--include-sql`. A caller outside its scope sees neither
   the Example nor its SQL even with opt-in. After `ariadne review`, the authorized
   caller sees it without the marker; neither operation repins existing calculations.
10. **`promote`, no join.** `SELECT status, SUM(amount) FROM retail.main.orders GROUP BY status`
    with `--name revenue_by_status` yields `retail::orders.revenue_by_status` =
    `SUM(source.amount)` and suggests preview with `--by status`. With unchanged data
    and applicable Policies, `query` after approval returns the same numbers as `sql`.
11. **`promote`, join.** `SELECT c.region, SUM(o.amount) FROM retail.main.orders o LEFT JOIN
    retail.main.customers c ON o.customer_id = c.id GROUP BY c.region` writes the metric, not the
    join. Preview uses `--by customers.region` and keeps an unmatched order in the
    NULL group, just like the input. An `INNER JOIN` or unsupported predicate refuses
    `not_representable`; traversing `customers → orders` over the reverse edge refuses
    `join_reverses_relationship`; with `orders` as the base, `SUM(c.credit_limit)`
    refuses `measure_not_on_fact`. An undeclared edge refuses `undeclared_join`.
12. **`promote --last`.** Redaction inside an aggregate refuses `literal_required`.
    A redacted value in a supported fact filter yields an incomplete preview that names
    the missing input. A latest successful record with no SQL refuses `sql_unavailable`
    even if an older record has SQL.
13. **`gaps`.** After one SQL shape occurs three times, then a different query is run,
    `gaps` reports count 3, tables read and normalized SQL only. If the only served
    metric is `row_count` and there is no matching Example, coverage is unknown and the
    guidance is rerun-and-save, not `--last`. The served state is byte-identical.
14. **Unchanged guards.** The existing grain/fan-out, containment, read-only and
    redaction tests pass untouched; expected numbers come from the existing independent
    oracles.

## 7. Artifact reconciliation

- **Proposed Ariadne ADRs** (0029 and 0030 are 0040's):
  - [0031: Built-in drafting; host agents optional](../../products/ariadne/project/adr/0031-built-in-drafting.md).
  - [0032: Optional Ossie converters and file exchange](../../products/ariadne/project/adr/0032-ossie-file-imports.md).
  - [0033: SQL promotion keeps joins in the planner](../../products/ariadne/project/adr/0033-sql-promotion-planner-joins.md).
- **Reconciled:** umbrella 0037 now describes source-first drafting, opt-in Example SQL,
  file-only auto-ontology exchange and normalized gaps. 0040 §3.6 and B1 T7 use exact
  grants for preview without repinning; 0040 §4.4 preserves 0023's opt-in disclosure.
- **At delivery:** mark the old Example write methods in specs 0007/0023 as historical
  (existing records remain readable), and update the harness-drafting passages of
  spec 0024's onboarding and the packaged skill. The plan lists the exact passages.
- **Vocabulary:** Ariadne's glossary records *Deterministic Draft*, *Enrichment*,
  *SQL-to-Metric Draft*, *Gap Report* and the changed role of *Authoring Agent* and
  *Seed Notes*. Do not use the legacy *Promotion* term for SQL-to-metric drafting.

## 8. Delivery and verification

- **B3 and C land as one candidate** with one plan, one worktree, one independent
  review and one full CI gate (owner decision 2026-11-24). The plan references the B3
  spec and this spec as its sources; both must be approved before it is written.
- The candidate starts after B2 lands: it needs `sql`, the run log and `context`
  (0040 §4) for §4, and it carries no part of B2.
- The LLM stub of §6.7 is a local test double; no real provider is called in CI.
- Converter extras are built and import-tested in CI with pinned converter versions;
  the Wide World Importers export is a committed fixture.
- Sub-agents run as Herdr panes in the project's tab (0040 §8).

## 9. Resolved decisions and the remaining prerequisite

- **Resolved 2026-11-24:** B3 lands with C; one candidate.
- **Prerequisite:** the B3 spec (tier K, `review`/`revert`, workspace) must be written
  and approved before the combined plan. It must specify the isolated publication,
  version and authorization route §3.4.7 and §4.1 rely on, without changing a pinned
  analytics/Policy association or widening visibility.

## 10. Capture checkpoint

- **Vocabulary:** §7.
- **Decisions:** ADR-0031, 0032, 0033.
- **Behavior:** §3–§5; acceptance examples §6.
- **Uncertainty:** the B3 spec is the open prerequisite (§9). The plan will check the
  provenance field (§3.4.6), bare `draft` dispatch alongside B1's subcommands, and
  optional dependencies for native document intake and converter fixtures.

Planning Contract version 1; installed provenance `unknown`.
