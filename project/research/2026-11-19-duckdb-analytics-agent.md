# duckdb-analytics-agent: what Ariadne can reuse

Date: 2026-11-19. Evidence for [spec 0037 r2](../specs/2026-11-18-0037-simple-ariadne.md).

Source: `github.com/early-signal-tech/duckdb-analytics-agent` ("Duck Harness"). The
README, `duckdb_agent/sources.py` and `duckdb_agent/sql.py` were inspected, together
with the author's trace-schema diagram, which shows `agent_runs`, `agent_traces`,
`tool_calls`, `api_calls`, `replay_sql` and `table_choices`. Nothing was executed.
The parallel session's earlier analysis was relayed by intercom on 2026-11-19.

## What it is

A text-to-SQL agent with its own loop: Claude writes read-only DuckDB SQL and iterates
until it can answer, and every step is traced into a DuckDB database. It is evaluated
on the 22 TPC-H queries, graded Correct, Careful and Efficient.

## Reusable ideas (adopted in spec 0037 r2)

1. **`lock_down(conn, allowed)`** runs after all sources are attached:
   - `SET allowed_directories` to the data paths, including DuckLake `data_path`;
   - `SET enable_external_access = false`;
   - `SET lock_configuration = true`.

   After this, SQL cannot read other files or URLs (`read_csv('~/.env')`) and cannot
   attach, load, install or change settings. Together with `READ_ONLY` attaches and
   the single-statement check (`extract_statements`, allowing only SELECT and EXPLAIN
   of a SELECT), this is a runtime guard rather than a ban on SQL. Ariadne sets none
   of these three settings today (grep, 2026-11-19).
2. **A trace schema in DuckDB.** Each tool call records `input_sql`, `table_names`
   (parsed from the SQL), `success`, `error_type`, `truncated` and `duration_ms`. The
   `table_choices` view records, per run and table, whether the table was listed,
   described, sampled or queried, whether it appeared in the answer, and whether it
   was dropped. The authors observe that wrong answers usually come from the wrong
   table, not from wrong SQL. In Ariadne, the context pack is meant to prevent that,
   and the run log measures it.
3. **An evaluation set:** the TPC-H questions with reference results and the
   Correct/Careful/Efficient grading. This is a later candidate, together with the
   auto-ontology-eval/BIRD harness.

## Not adopted

- The agent loop, prompts, context editing and stdin JSON protocol. Ariadne serves
  host agents (ADR-0027).
- `replay_sql`. Ariadne's governed SQL is compiled deterministically. Ad-hoc SQL is
  logged verbatim.
- The Quack trace server, and storing result rows in traces. The owner chose a run log
  without result rows.

## Open (spike before sub-spec B)

Whether `lock_down` works with Ariadne's trusted native DuckDB catalogs, whose views
reference backing files (ADR-0022), with Delta, Iceberg and DuckLake, and with scoped
S3 storage profiles (ADR-0023), and which `allowed_directories` each source type
needs.
