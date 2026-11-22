# Specification 0040: One CLI, simple governance, guarded ad-hoc SQL

**Status:** proposed, revision 1, 2026-11-22. This is sub-spec B of the
[approved umbrella spec 0037 r2](2026-11-18-0037-simple-ariadne.md). It is not approved.
An external design review (`openai-codex/gpt-6.2-sol`) runs before owner approval.

**Owner decisions (Pi conversation, 2026-11-19 to 2026-11-22):**

- **Approval and agents:** a single interactive TTY approval; agents never approve.
- **Ad-hoc SQL** replaces `define_metric` and `query_records`. Fan-out produces a
  **warning**, never a refusal.
- **Answer Examples** are saved on request.
- **Run log:** on by default, without result rows.
- **Delivery:** B is split into **B1 → B2 → B3**, each with its own plan, candidate and
  landing.
- **Tier K** goes live by **automatic publication**. The calculation half of the Bound
  Release stays fixed.
- **Spec review:** an external review runs before approval.

**Evidence:**

- `project/research/2026-11-19-lockdown-spike.md`: DuckDB 1.5.6 probe plus a 2.x
  local re-probe.
- The parent's live DuckDB 2.0.0 probe from 2026-11-20 (run directory
  `live-probe-2x.md`; appended to the research note in B2). With `lock_down` alone,
  **G1** (S3 `..` traversal), **G3** (`postgres_query`), **G4** (`CREATE SECRET` with a
  foreign endpoint) and **G5** (`COPY … TO s3://`) **remain open** on the query path.
- Spec 0039, as landed (origin/main `970b9fa`): validation connections are locked
  (`sources.lock_down`). The governed query path (`query.py`) is not locked.

## 1. Goal

A data owner goes from an empty directory to governed answers with five commands. They
never handle IDs, revisions, digests, namespaces or selector files. An agent answers
any question with guarded ad-hoc SQL. The answer is labeled `governed:false` and says
what it is based on.

```text
ariadne init
ariadne add data/orders.parquet          # B1: declare a source into the active draft
ariadne preview revenue                  # B1: query the draft (governed:false)
ariadne approve                          # B1: one interactive confirmation → served
ariadne query revenue                    # governed:true

ariadne context "churn by cohort"        # B2: context pack
ariadne sql "SELECT …"                   # B2: guarded ad-hoc SQL (governed:false)
```

## 2. Non-goals

- Automatic drafting from profiles or documents, `ariadne add` drafting, imports,
  `save-example`, `promote` and `gaps`. These belong to sub-spec C. B1's `add` only
  declares the source.
- Renaming or restructuring Lumio's own CLI, SDK or published formats. Lumio remains an
  independent product. B changes only how Core consumes Lumio publication.
- Network services beyond the existing MCP transport. The workspace server's browser
  review stays its confirmation channel (B3).
- Backward compatibility: there are no aliases for removed executables, MCP tools or
  CLI flags (umbrella §2).

## 3. B1 — One CLI, one active draft, one approval, preview

### 3.1 Executables and commands

1. `ariadne-data` ships **one** console script: `ariadne`. The following are removed
   with no aliases:
   - `ariadne-validate`
   - `ariadne-serve`
   - `ariadne-analyst-mcp`
   - `ariadne-authoring-mcp`
   - `ariadne-init`
   - `ariadne-skill`
   - `ariadne-profiler`
   - `ariadne-authoring`
   - `ariadne-admit`
2. B1 provides these subcommands. Each one prints human-readable text by default and
   JSON with `--json`.

| Command | Replaces | Meaning |
|---|---|---|
| `init [DIR]` | `ariadne-init`, `ariadne setup` | §3.2 |
| `add <path\|url\|dsn>` | `propose-sources` (+ approve) | Declares a source in the active draft (no drafting) |
| `draft [status\|edit FILE\|discard]` | `ariadne-authoring start/edit/inputs` | Shows the active draft, applies a typed edit file, or discards the draft |
| `validate` | `ariadne-validate`, `ariadne-authoring validate` | Validates the active draft |
| `diff` | `ariadne-authoring review` | Human-readable summary of the draft against the served state |
| `preview <metric> [--by …]` | — | §3.5 |
| `approve` | `approve-sources`, `ariadne-admit` (+ `--confirm`) | §3.4 |
| `reject` | — | Discards the active draft after confirmation |
| `status` | `ariadne status` | Served revision, draft state, unreviewed knowledge (B3) |
| `query <metric> [--by …]` / `metrics` / `datasets` / `search` | `get-metric`, `list-metrics`, `list-datasets`, `search-context` | The governed query surface (unchanged semantics) |
| `serve [--toolset …]` | `ariadne-serve`, `*-mcp` | MCP transport (optional extra) |
| `skill install\|status\|path` | `ariadne-skill` | Unchanged |
| `profile` | `ariadne-profiler` | Unchanged output |
| `migrate` | `ariadne migrate` | Unchanged (spec 0039 §7) |

3. The MCP surface keeps the query and authoring operations. It loses `define_metric`
   and `query_records` (B2 replaces them with `sql`). It gains `preview` and
   `draft_status`. MCP never exposes `approve`, `reject` or any source-approval
   operation.

### 3.2 `ariadne init`

1. `ariadne init` works in an empty or existing directory. It:
   - creates a Git repository if none exists;
   - sets a **repository-local** Git identity only if no identity resolves, after one
     prompt; with `--yes` and no identity it refuses with the exact `git config`
     commands;
   - generates a random `urn:uuid` namespace;
   - writes the private profile to `~/.config/ariadne/<namespace-uuid>.json`;
   - writes `context_integration.yaml` with the current highest supported
     `support_revision` and empty Policy bindings;
   - initializes the native Lumio Knowledge Base;
   - commits once.
2. Re-running `init` on an initialized project validates it and changes nothing.
   Conflicting existing files are refused, with each one named. It never resets or
   adopts foreign content silently.

### 3.3 One active draft

1. A project has **at most one active draft**: one Authoring Proposal created implicitly
   by the first mutating command (`add`, `draft edit`, `migrate`). Every command uses it
   without IDs or revisions.
2. **Optimistic concurrency is internal.** Each mutating command records the draft
   revision it read. If the draft moved since then, for example because of another
   process, an agent or a manual Git change, the command refuses. The message tells the
   user to run `ariadne draft status` and re-apply. Nothing is overwritten.
3. If the served state advances while a draft exists, the draft becomes **stale**.
   `validate`, `preview` and `approve` then refuse until the user runs
   `ariadne draft rebase`. That command performs the existing reconcile semantics:
   - the clean draft head is rebased onto the served revision;
   - validation and review are invalidated;
   - conflicts are refused, with the files named, and never auto-resolved.
4. Proposal identities, revisions and digests remain in `.ariadne/` and Git. They appear
   in `--json` and `status`, never as required arguments.

### 3.4 `ariadne approve`

1. `approve` is the **only** route to served state for calculation changes (tier C):
   - sources, semantic models, `graph.yml`;
   - Policies and bindings;
   - contracts and contract bindings;
   - Computation pages;
   - mapping confirmations.

   It merges the previous "source approval" and "admission preview + confirm" steps.
2. **Order:**
   1. Validate the current draft revision, reusing a matching cached validation.
   2. Build the review summary (the former `ariadne-admit` display content, including
      mapping selections and the composite digest).
   3. Print it.
   4. Ask one question on the controlling TTY.
   5. On "yes", admit exactly the reviewed revision and digest, then activate atomically
      (the existing `admit_revision` guarantees).
3. **Interactive confirmation is mandatory.**
   - Without a TTY on stdin **and** stdout, `approve` refuses.
   - An environment variable or flag that skips the prompt does not exist.
   - The confirmation records the resolved Git identity, the time and the approved
     digest in the admission descriptor.
   - The packaged skill and the MCP surface instruct agents never to run `approve`.
4. **Source approval is folded in.** The approval binds the complete resolved source
   identity set of the draft, exactly as `approve_sources` did, so a changed endpoint or
   DSN destination needs a new `approve`.
   - **Before approval, profiling reads only already-approved sources.** A newly
     `add`ed source can be profiled only after it is approved.
   - B1 therefore allows `approve` of a **sources-only** draft. C relies on this to
     profile after approval.
5. Mapping confirmations (the former `--confirm-mapping`) are shown in the summary as a
   numbered list. They are confirmed through `--confirm-mapping` selections on
   `approve`, under the same rules. A hypothesis is never confirmable.
6. A failure anywhere leaves the previous served state intact. This is the existing
   atomic activation guarantee.

### 3.5 `preview`

1. `ariadne preview <metric> [--by dims] [--filter …]` and MCP `preview` compile and run
   the metric **from the active draft revision**. They use the same compiler, grain and
   fan-out guard, deadlines and result caps as `query`.
2. The connection is built from **approved sources only**. Preview never opens a source
   that is new in the draft. It is locked with `sources.lock_down` exactly like
   validation connections.
3. The result carries `governed:false`, `draft_revision` and `served_revision`. It is
   never stored as an Answer Example and never cached as an answer.
4. If the draft does not validate, preview refuses with the validation errors.

### 3.6 Removals in B1

- the executables in §3.1;
- the two-step admission CLI (preview plus `--confirm`, the digest and revision flags);
- `propose_sources`/`approve_sources` as separate operations and MCP tools;
- the Staging/Promotion remnants and the legacy `Proposal` route.

Code and tests that serve only these surfaces are deleted. The behavior they protected
(exact-revision binding, digest check, atomic activation, source identity binding) stays
tested through the new commands.

## 4. B2 — Guarded ad-hoc SQL, context pack, run log

### 4.1 `ariadne sql` / MCP `sql`

1. `ariadne sql "<SQL>"` and MCP `sql` run **one** agent-written query over the
   **served** state's approved sources. The result always carries:
   - `governed: false`;
   - `tables`: the relations read;
   - the applicable `policies` and `caveats` for those relations;
   - `unreviewed` (B3);
   - `warnings`.
2. **Three guard layers** apply, all of them before and during execution:
   1. **Statement guard.** `duckdb.extract_statements` yields exactly one statement of
      type `SELECT`, or `EXPLAIN` of a `SELECT`. Anything else is refused before
      parsing.
   2. **Parse-tree guard.** This runs on DuckDB's own `json_serialize_sql` of the
      statement, not on sqlglot.
      - Every relation is a `BASE_TABLE` that resolves case-insensitively, under
        DuckDB's search path, to a catalog, schema and table of the served registry, or
        it is a CTE visible at that point.
      - Table functions (`TABLE_FUNCTION`) are refused, including `read_*`, `glob`,
        `postgres_query`, `duckdb_secrets` and `query`.
      - String and path relations are refused.
      - If serialization fails, the query is refused.
   3. **Locked connection.** The query runs on a connection built from the served
      registry and sealed with `sources.lock_down`. Before the lock, the session
      creates **no** secrets beyond the registry's profiles. After the lock,
      `lock_configuration` prevents `SET`, `ATTACH`, `INSTALL` and `LOAD`.
3. The existing deadline, result row and byte caps, and the single-statement EXPLAIN
   bind apply.
4. **Warnings, not refusals:**
   - a join that is not declared in the served model or `graph.yml`;
   - a join whose declared cardinality fans out an aggregated relation (one-to-many
     into an aggregate);
   - unaggregated reads above the row cap;
   - reads of relations with required Policies that the query does not filter on, by
     name.

   Each warning names the relation and the relationship.
5. **Postgres.** A Postgres source is reachable only through its attached catalog. The
   parse-tree guard refuses `postgres_query`/`postgres_scan`. The approval summary
   (§3.4) recommends a least-privilege role.

### 4.2 `ariadne context` / MCP `context`

`ariadne context "<question>"` returns a bounded context pack (default 16 000
characters, with truthful omission disclosure). It contains:

- relevant datasets and columns with descriptions and observed values;
- relationships with cardinality;
- filter rules and required Policies;
- approved metrics that nearly match, with their identities;
- the most relevant Answer Examples, including their SQL.

Ranking uses the existing Lumio search (lexical, or BM25 when configured). The pack is
read-only and never changes retrieval state.

### 4.3 Run log

1. These operations append one record to `.ariadne/runs.duckdb`, which is git-ignored:
   `query`, `preview`, `sql`, `context` and refusals.
2. **What a record holds:**
   - time, operation and question, when given;
   - the SQL, the relations read and the served or draft revision;
   - the outcome: ok, refused (with its class) or error;
   - warnings, row count and duration.
3. **What a record never holds:** result values or credentials. Retention is 90 days,
   configurable as `run_log.retention_days`. The log is disabled by
   `run_log.enabled: false` in the project's private profile.
4. The log is runtime state. Nothing reads it to change retrieval, models or examples.
   `ariadne gaps` (C) only reads it.

### 4.4 Removals in B2

`define_metric`, `query_records` and their CLI and MCP surfaces, Ad-hoc Metric staging,
and the record-query paths are removed. Their safety tests are migrated to `sql` where
the protected behavior persists: source containment, caps and deadline.

## 5. B3 — Knowledge tier K, review/revert, workspace

### 5.1 Change classification

A draft change is **tier K (knowledge)** only if **every** changed file is a Lumio page
that is **not**:

- a Policy page bound by any Policy Binding;
- a Computation page;
- a metric page referenced by `metric_ref`;
- a page carrying `ariadne_profile` evidence or attestation claims;
- a source, model, `graph.yml`, contract, binding or selector file.

Any other change, or a mixed one, is **tier C** and needs `approve`.

### 5.2 Automatic publication for tier K

1. `ariadne draft publish-knowledge` publishes a validated tier-K draft. MCP tool:
   `publish_knowledge`. Agents may call it; that is the point of tier K. It:
   - validates the draft with the normal Lumio and Core page gates;
   - publishes a new **Lumio Published Version** through the existing Lumio publication
     route;
   - creates a new **Bound Release** whose calculation identities (semantic snapshot,
     source identity, Policy and Computation bindings, evidence) are **byte-identical**
     to the current one, and whose knowledge identity points to the new Published
     Version;
   - activates it atomically.

   The activation is recorded with `origin: knowledge-auto` and is **not** a human
   admission.
2. If any calculation identity would differ, the command refuses and directs the user to
   `approve`.
3. Every page changed by an automatic publication is listed as **unreviewed** in the
   Bound Release until a human countersigns it. Every answer whose context includes an
   unreviewed page lists it under `unreviewed: [{page, published_version}]`.
4. `ariadne review [PAGE…]` (TTY-only, like `approve`) shows the unreviewed diffs and
   countersigns them. The command writes a new Bound Release with identical identities
   that clears the countersigned pages from `unreviewed`. It never changes content.
5. `ariadne revert PAGE…` creates a tier-K draft that restores each named page to its
   last countersigned content (or removes a page that never had any) and publishes it
   through §5.2.1. `revert` is TTY-only.

### 5.3 Workspace server

`lumio-workspace` adopts the same rules:

- Tier-K contributions are published after their validation, marked unreviewed. The
  browser review countersigns them.
- Tier-C contributions keep the existing browser review as the single human
  confirmation that replaces `approve`.
- The analytics adapter maps its source request and review onto the same single approval
  (one confirmation per combined change).

## 6. Invariants

1. `governed:true` appears only for `query` on approved definitions in the served Bound
   Release.
2. Results of `preview`, `sql` and `context` always carry `governed:false`.
3. No agent-reachable surface performs tier-C approval or countersigning.
4. `approve`, `review` and `revert` require an interactive TTY.
5. Every connection that reads approved sources outside the governed query (validation,
   preview, `sql`, profiling, inspection) is locked to the approved registry.
6. The governed query keeps the compiler-only SQL path and its existing guards.
7. Credentials are referenced by variable name only, and redaction is preserved in every
   new message and log.
8. Served state changes only through `approve`, `publish-knowledge` or `review`/`revert`.
   Each activation is atomic, and a failure leaves the previous state intact.

## 7. Acceptance examples

### B1

1. A fresh directory runs:

   ```text
   ariadne init
   ariadne add data/orders.parquet
   ariadne approve          # sources-only, TTY "yes"
   ariadne draft edit model.yaml
   ariadne validate
   ariadne preview orders.revenue
   ariadne approve          # TTY "yes"
   ariadne query orders.revenue
   ```

   The final query returns `governed:true`. No step required an ID, revision, digest,
   namespace or YAML selector.
2. `ariadne approve` with stdin or stdout not a TTY refuses, and nothing changes.
   MCP lists no approve/reject/review/source-approval tool. The removed executables no
   longer exist in the installed wheel.
3. Two concurrent `draft edit` calls: the second refuses as stale with a hint, and
   nothing is overwritten.
4. After the served state advances, `preview` refuses until `ariadne draft rebase`. A
   conflicting rebase refuses with the files named.
5. `preview` of an edited metric returns `governed:false` with `draft_revision`, while
   `query` keeps serving the old definition until `approve`.
6. A draft that adds a source with a changed DSN destination cannot be previewed against
   that source. After `approve`, the new identity is bound.
7. The existing admission guarantees still hold through `approve`: exact-revision
   binding, a stale or edited revision refuses, and a failed activation keeps the
   previous state. These are migrated tests.

### B2

8. `ariadne sql` refuses each of the following:
   - `read_csv('~/.env')`
   - `FROM 's3://approved/sales/../private/x.parquet'`
   - `postgres_query('pg', '…')`
   - `glob('*')`
   - `COPY … TO`
   - `ATTACH`, `SET`, `CREATE SECRET`
   - a second statement
   - a table outside the registry

   Each refusal is logged as refused, without values.
9. A window-function cohort query over approved sources answers with `governed:false`,
   `tables`, and the required Policies of those tables.
10. A join that fans a one-to-many relationship into a `SUM` returns its rows **and** a
    fan-out warning that names the relationship.
11. Against live SeaweedFS and Postgres (CI S3 job), G1, G3, G4 and G5 are refused by the
    guard layers. With the parse-tree guard disabled by a scratch fault, G1 file reads
    outside approved paths are still refused by the lock (G4 and G5 by the statement
    guard).
12. `.ariadne/runs.duckdb` holds the SQL, tables and outcome but no result values. A
    90-day retention purge works. Disabling the log stops writes.
13. `ariadne context` returns a pack within budget that contains the relevant dataset,
    relationship and an Answer Example with SQL. Omissions are disclosed.

### B3

14. Editing a guide page and running `publish-knowledge` makes it served immediately.
    A governed answer citing it lists it under `unreviewed`. The calculation identities
    of the Bound Release are byte-identical to the previous release.
15. Editing a metric page, a bound Policy page or a model in the same draft makes
    `publish-knowledge` refuse and point to `approve`.
16. `ariadne review` (TTY) clears `unreviewed` without content change. `revert` restores
    the last countersigned content and publishes it.
17. In the workspace server, a tier-K contribution is visible after validation as
    unreviewed. A tier-C contribution still needs the browser review, and that one
    confirmation activates it.

## 8. Artifact reconciliation

- **New ADRs (Ariadne):**
  - **ADR-0029 "Single interactive approval and change tiers"** supersedes the gate
    structure of ADR-0010 (separate source approval), ADR-0016, ADR-0024 and the
    two-step part of ADR-0026, and the corresponding parts of shared ADR-0029 where
    they conflict.
  - **ADR-0030 "Guarded ad-hoc SQL with three layers"** supersedes ADR-0005 and
    ADR-0019 and amends ADR-0015 (on-request examples are C).
- **Superseded headers** go on the specs these replace in part: 0009 (modular Core Git
  authoring), 0014 (bounded records), 0027 (Git-only authoring CLI parts), 0029
  (two-step release confirmation), 0032 §ad-hoc parts, 0033 where they conflict. Each
  gets a one-line scope note. Plan reconciliation happens in each B plan.
- **CONTEXT.md:**
  - Add: Draft, Preview Query, Knowledge Change (tier K), Calculation Change (tier C),
    Unreviewed Knowledge, Ad-hoc Query, Context Pack, Run Log.
  - Redefine: Source Approval (folded into approval), Git Review Admission ("Approval"),
    Bound Release (origin: human approval or knowledge-auto).
  - Remove: Ad-hoc Metric, Ad-hoc Record Query, Proposal, Staging, Promotion.
- **Lumio:** no SDK contract change is planned. If B3 needs one, for example for a
  knowledge-only re-binding, it is specified as an additive amendment of Lumio ADR-0030
  before B3's plan.

## 9. Order, delivery and verification

- B1, B2 and B3 are separate candidates. Each has a plan, an isolated worktree, an
  independent review and a full CI gate, and each is landed before the next starts.
- B2 depends on B1 (one CLI, locked preview). B3 depends on B1 (draft and approval).
- Every guard and the locked connection get a live CI check where the CI S3 and Postgres
  services exist; this extends the existing `onboarding-s3-compat-journey` job.

## 10. Capture checkpoint

- **Vocabulary:** see §8 (CONTEXT.md).
- **Decisions:** ADR-0029 and ADR-0030, as above.
- **Behavior:** §3–§6, with the acceptance examples in §7.
- **Uncertainty, to be resolved in the design review or by the owner before approval:**
  - (a) whether `review` can countersign selected pages or only all of them (proposed:
    selected, default all);
  - (b) whether `approve` of a sources-only draft is acceptable as the profiling gate
    (proposed: yes, see §3.4.4);
  - (c) the exact Lumio publication call for tier K (existing `publish_and_verify`; the
    review confirms that it needs no SDK change).

Planning Contract version 1; installed provenance `unknown`.
