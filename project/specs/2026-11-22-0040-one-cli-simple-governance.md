# Specification 0040: One CLI, simple governance, guarded ad-hoc SQL (B1 + B2)

**Status:** owner-approved, revision 3, 2026-11-22 ("freigabe" after presentation of r3). Approval authorizes the B1 plan and supervised B1 execution in an isolated candidate; integration/publication still need the owner. The r2 recheck
(`s0040-review/recheck.md`) returned five bounded clarifications, all incorporated in
r3: a source grant is separate from release activation, the workspace callers, the r4
upgrade outcome, log refusals carry no text, and the warning example. This is sub-spec B of the
[approved umbrella spec 0037 r2](2026-11-18-0037-simple-ariadne.md).

Revision 1 received a design review from `openai-codex/gpt-6.2-sol`, and the verdict
was "revise first". The review is stored at
`~/.local/state/ariadne-runs/s0040-review/review.md`. Revision 2 incorporates all of its
must-fix findings that apply to B1/B2, together with the owner's decisions below. A
short recheck of r2 runs before owner approval.

**Owner decisions, Pi conversation 2026-11-19 to 2026-11-22:**

- **Approval:**
  - single interactive approval;
  - agents never approve;
  - **a new source gets its own first approval before any read** ("Eigene
    Quellen-Freigabe zuerst");
  - TTY approval is a **documented operator-consent convention, not
    authentication** ("Konvention, klar dokumentiert").
- **Ad-hoc SQL:**
  - replaces `define_metric` and `query_records`;
  - fan-out produces a warning, not a refusal.
- **Run log:** stores **normalized SQL with literals removed**, never the question text
  ("SQL normalisiert, Literale entfernt").
- **B3** (tier K, `review`/`revert`, workspace) moves to its **own later spec**
  ("B3 in eigene spätere Spec"). This spec covers B1 and B2. Each gets its own plan,
  candidate and landing, in the order B1 → B2.

**Evidence:**

- `project/research/2026-11-19-lockdown-spike.md`.
- The parent's live DuckDB 2.0.0 probe (run directory
  `d0039-20261119/live-probe-2x.md`; appended to the research note in B2). G1, G3, G4
  and G5 remain open with lock alone. **The lock does not reliably contain G1 without
  the parse guard** (design review, finding 4).
- Landed spec 0039 (`970b9fa`): validation, profiling and inspection connections are
  locked; the governed query path is not.
- The design-review parser observations on DuckDB 2.0.0:
  - `FROM` shorthand is a `SELECT`;
  - `SHOW`, `DESCRIBE` and `SUMMARIZE` are `SELECT` with `SHOW_REF`;
  - simplified `PIVOT` is `MULTI`;
  - `UNNEST` is a `TABLE_FUNCTION` in `FROM` and a `FUNCTION` in the projection;
  - scalar macros appear as `FUNCTION`;
  - single-quoted and unqualified relations can serialize to the same `BASE_TABLE`
    fields;
  - `EXPLAIN` and `EXPLAIN ANALYZE` do not serialize.

## 1. Goal

**Owner path, new data:**

```text
ariadne init
ariadne add data/orders.parquet      # declare a new source in the active draft
ariadne approve                      # sources-only approval: offline identity, TTY
#  … draft the model (by hand now; automatically in sub-spec C) …
ariadne validate
ariadne preview orders.revenue       # governed:false, from the draft
ariadne approve                      # calculation approval
ariadne query orders.revenue         # governed:true
```

For a change that touches no new source, one `approve` suffices. No step requires an ID,
revision, digest, namespace or selector file.

**Agent path:** `ariadne context …` and `ariadne sql …` answer any question over approved
sources with `governed:false` and state what the answer rests on.

## 2. Non-goals

- **Moved to the B3 spec:**
  - knowledge tier K;
  - automatic knowledge publication;
  - unreviewed-knowledge tracking;
  - `review`/`revert`;
  - the workspace server.

  Until then the served state changes only through `approve`.
- **Sub-spec C:** automatic drafting, imports, `save-example`, `promote` and `gaps`.
- **Lumio:** no change to its CLI, SDK, publication formats or ADRs.
- **Not a sandbox:** B does not make `approve` a sandbox against a malicious local
  process with the operator's account (§3.5). It does not protect against malicious
  operator-approved native catalog definitions either (ADR-0022 trust boundary).
- **Backward compatibility:** no aliases for removed executables, tools or flags
  (umbrella §2).

## 3. B1: one CLI, one active draft, approval, preview

### 3.1 Executables and the complete public surface

1. `ariadne-data` ships one console script, `ariadne`. The executables `ariadne-validate`,
   `-serve`, `-analyst-mcp`, `-authoring-mcp`, `-init`, `-skill`, `-profiler`,
   `-authoring` and `-admit` are removed.
2. **The B1 CLI is exhaustive.** Each command prints text by default and JSON with
   `--json`. `serve` is exempt: it is the MCP transport, not a table command. Its
   stdout carries the MCP protocol, and it takes no `--json`. (Owner decision
   2026-11-23 at B1 review R1.)

| Command | Meaning |
|---|---|
| `init [DIR]` | §3.2 |
| `add <path\|url\|dsn> [--name N] [--type T] [--storage S]` | Declare a source in the active draft. No reads. |
| `draft status` | Active draft, generation, base served revision, stale or not, validation state. |
| `draft edit FILE` | Apply one typed edit file (the existing typed edit kinds) to the active draft. |
| `draft rebase` | §3.3.4 |
| `draft discard` | Discard the active draft after a confirmation (TTY or `--yes`). Its branch is kept as `ariadne/discarded/<generation>`. |
| `validate` | Validate the active draft at its current generation. |
| `diff` | Human-readable summary of the draft against the served state (the former review report). |
| `preview <metric> [--by D…] [--filter F…]` | §3.6 |
| `approve [--confirm-mapping SEL…]` | §3.4–3.5 |
| `status` | Served revision, its approval record, draft state. |
| `query <metric> [--by …] [--filter …]` | Governed query (unchanged semantics of `get_metric`/`query_metrics`). |
| `detail …` | Governed detail query (unchanged semantics of `query_detail`). |
| `metrics`, `datasets`, `search <text>`, `page <path>` | Discovery (unchanged). |
| `serve [--toolset analyst\|authoring\|combined] [--http …]` | MCP transport (optional extra). |
| `skill install\|status\|path` | Unchanged. |
| `profile` | Profile **approved served** sources of a managed project. The old `--db`/`--sources` inputs are not supported on a managed project. |
| `migrate` | Spec 0039 §7, adapted to §3.3 (writes into the active draft). |

3. **MCP surface after B1.** The read tools keep their names:

   - `discover`, `list_metrics`, `search_context`, `list_context_pages`,
     `read_context_page`, `get_metric`, `list_datasets`, `query_metrics`, `query_detail`,
     `save_example`, `search_examples`, `resolve_term`;
   - authoring: `authoring_read_artifact`, `authoring_edit_proposal` (now acting on the
     active draft without IDs), `authoring_inputs`, `authoring_refresh_schema`,
     `authoring_inspect_mapping`, `authoring_resolve_term` (also on the active draft,
     without a proposal ID).

   B1 **adds** `draft_status` and `preview`. B1 **removes** `authoring_propose_sources`;
   agents propose a source by writing the same typed source edit through
   `authoring_edit_proposal`. No MCP tool approves, rejects, discards or grants a
   source. `define_metric`/`query_records` stay until B2 replaces them.

### 3.2 `ariadne init`

1. `init` creates a Git repository if none exists. If no Git identity resolves, it
   prompts once and sets a repository-local identity. With `--yes` and no identity, it
   refuses and prints the exact `git config` commands.
2. It generates a random `urn:uuid` namespace and writes the private profile to
   `~/.config/ariadne/<uuid>.json` (the Lumio private-profile schema, unchanged), plus
   an Ariadne-owned sibling `~/.config/ariadne/<uuid>.ariadne.json`. Both are mode 0600,
   created atomically; the sibling has a strict schema, and both paths are recorded under
   `.ariadne/`. (Clarified during B1 execution on 2026-11-22: the Lumio SDK profile
   refuses unknown keys, and B makes no SDK change.) The Ariadne sibling holds:
   - the publication destination (default `~/.local/share/ariadne/published/<uuid>/`);
   - the default Visibility Scope `public`;
   - the run-log settings.
3. It writes `context_integration.yaml` with the highest supported `support_revision`
   and empty bindings, and initializes the native Lumio Knowledge Base.
4. It makes **one commit that contains only the files it created**. Staged or
   unstaged unrelated work in an existing repository is neither committed nor changed.
   If any target file already exists with different content, `init` refuses and names
   it.
5. Re-running `init` on an initialized project validates it and changes nothing.

### 3.3 One active draft: project-wide compare-and-set

1. **The draft slot.** `.ariadne/draft.json` (project-locked) holds `{generation,
   proposal, candidate_revision, base_served_revision}`. The CLI, MCP authoring tools
   and `migrate` all go through this one slot:
   - **The first mutating command creates the slot.** It uses compare-and-set on
     "no slot", so it fails if a slot exists. Two concurrent first writes produce
     exactly one draft; the loser refuses with a stale message and rereads.
   - **Every mutating operation states the generation and candidate revision it read.**
     Mismatches refuse, and nothing is written. Every finalizing operation (`validate`,
     the finalize commit and approval activation) is pinned to that generation and
     candidate revision **and** to the served revision it was based on.
   - **`draft discard`** retires the slot and keeps the branch under
     `ariadne/discarded/<generation>`. A later write never resurrects a discarded
     draft.
2. **The existing proposal machinery stays underneath.** One proposal per generation;
   proposal IDs never appear as arguments. MCP authoring tools no longer accept
   proposal or base IDs.
3. **Stale drafts.** When the served revision advances past `base_served_revision`, the
   draft is stale. Then `validate`, `preview` and `approve` refuse until
   `draft rebase` succeeds.
4. **`draft rebase`.**
   - Under the project lock it rebases the clean draft head onto the served revision in
     the proposal worktree. On success it records the new candidate revision and the new
     base, increments the generation, and invalidates any validation and review.
   - On conflict it aborts the rebase. The draft and its branch stay exactly as before,
     and the conflicting files are named.
   - It never auto-resolves conflicts.
5. **No dangling approval.** An approval activation pins the generation, candidate
   revision and served base it displayed. If any of them changes between display and
   "yes", for example through an edit during the prompt, activation refuses and nothing
   changes.

### 3.4 Approval order and source consent

1. **Two kinds of approval content.** A draft whose diff against the served state
   **adds or changes a source identity** is a **source approval**. This covers a new
   source, a changed path, endpoint, DSN destination or storage binding, and a new
   storage profile. A source approval may contain **only** source declarations and
   their storage profiles. If it contains anything else, `approve` refuses and asks the
   user to approve the sources first.

   Every other draft is a **calculation approval**. It covers models, `graph.yml`,
   Policies and bindings, contracts, Computation pages, mapping confirmations and
   Lumio pages. It may only use **already approved** source identities.
2. **Source approval** (no reads before "yes"):
   1. Run offline checks only: registry validation, credential-free resolution of the
      exact effective identity (path or URI, DSN destination without credentials,
      endpoint and region of storage profiles), and scope checks.
   2. Display the exact identities and the delta against the served sources. Disclose
      that live checks are pending.
   3. Ask on the TTY (§3.5).
   4. On "yes", recheck the exact identity against the displayed one. Then open each
      new source **inside the approval transaction** for the bounded live checks
      (attach, catalog enumeration, existing containment checks).
   5. Only after all checks pass, record the **source grant** atomically in
      `.ariadne/source_grants.json`. That file is project-locked and append-only by
      generation. It holds each exact approved identity with its attribution, time and
      approved digest.

      A source grant is **not** a release activation:
      - the served Bound Release, its calculations and its pinned source bindings stay
        unchanged;
      - it authorizes bounded **reads for authoring only**: profiling, inspection,
        schema refresh and preview.

      The grant, the consumed draft generation and the new source baseline form **one
      recoverable transaction with a single commit point**: the approval journal is
      renamed to its committed form and the directory is synced. A failure before that
      point rolls all three back and is reported as a failure; a failure after it is
      cleanup and the approval is reported as successful. If the directory sync after
      the rename fails, the approval stays **pending**: the command reports "recovery
      pending", and a later operation retries the sync. The approval stands once the
      sync is confirmed. While the journal or the committed marker of an unfinished or
      interrupted approval exists, authoring reads that depend on grants refuse with a
      clear message instead of using the grants file. (Owner decision 2026-11-23 at
      B1 review R1; the pending rule for a failed sync was added the same day.)

      An interrupt that arrives while an interrupted approval is being rolled back is
      held until the cleanup has reached its outcome. For the interactive CLI (draft
      commands and the approval prompt) the outcome is reported before the interrupt is
      delivered. In the MCP server transports the interrupt shuts the server down once
      the cleanup has run: the state stays consistent, the reply may be lost, and the
      client runs `draft status` again to see the outcome. (Owner decision 2026-11-24 at
      B1 review R1.)
   6. The approved draft generation is **consumed**. The source declarations it
      contains are committed to the project as the new *approved source baseline*. The
      next edit starts a new draft generation on top of it, so a calculation draft sees
      the granted sources as already approved.
   7. **A changed identity never repoints served calculations.** A granted identity can
      replace the identity of a source that an admitted metric uses (a changed endpoint,
      DSN destination or path). Governed `query`/`detail` then either:
      - keep reading the identity bound by the **served release**, when that identity is
        still resolvable in the current environment; or
      - **refuse with a clear message** naming the source and the pending calculation
        approval, when the environment now resolves only the new identity (for example,
        the same `connection_env` or storage profile variables now point at B).

      They never silently read the new identity before a calculation approval admits a
      release bound to it. Preview uses the new identity. (Owner decision 2026-11-23 at
      B1 review R1: refusing is acceptable; no dual-credential mechanism is required.)
   8. On any failure, the served state and every grant stay as before. **No grant is
      created by a failed or refused approval.**
   9. Postgres sources are declared with a `connection_env` reference (ADR-0010).
      `add` never accepts an inline DSN with credentials; it refuses them and names the
      variable form.
3. **Calculation approval:**
   1. Validate the exact draft generation on locked connections over approved sources,
      reusing a matching cached validation.
   2. If validation's finalize step changes the candidate, the new revision is what is
      displayed. Nothing is activated under consent given for different bytes.
   3. Build the review summary (the former admission display, including mapping
      selections and the composite digest), print it and ask on the TTY.
   4. On "yes", admit exactly the displayed generation, revision and digest with the
      existing `admit_revision` guarantees, and activate atomically.
4. **Profiling, inspection and preview read only granted sources:** the identities
   bound by the served release, plus those in `source_grants.json`.
   `authoring_inputs`, `refresh_schema`, `inspect_mapping`, `profile` and `preview`
   resolve their grant from these two records, not from a proposal-local approval file.
   A calculation approval admits a release whose bound sources must all be granted;
   admission revalidates against exactly those identities. The proposal-local
   `approve_sources` record and its grant are removed.
5. **Mapping confirmations.** The former `--confirm-mapping` appears as a numbered list
   in the summary and is confirmed with `approve --confirm-mapping SEL…`, under the
   same rules as before. A hypothesis is never confirmable.

### 3.5 What the interactive confirmation is, and is not

1. `approve` and `draft discard` (unless `--yes`) require a TTY on stdin and stdout and
   ask one question. No flag or environment variable skips the approval prompt. The
   admission record stores the resolved Git identity as an **attribution label**, plus
   the time and the approved digest.
2. **The trust model is stated explicitly.** A process running under the operator's
   account, including a local agent with shell access, is trusted with the operator's
   permissions. The TTY prompt is an operator-consent convention, not authentication
   and not a sandbox.
3. **What B guarantees, and tests:**
   - No **shipped agent interface** can approve, reject, discard, grant a source or
     confirm a mapping. Shipped agent interfaces are the MCP tools, the packaged skill
     and the documented agent CLI commands (`context`, `sql`, `preview`, `query`,
     discovery, and the draft read and edit commands).
   - The packaged skill instructs agents never to run `approve`.
   - The remote alternative is the workspace server's separately authenticated browser
     review. Its credential, capability and one-use action binding stay unchanged and
     out of scope for B.

### 3.6 `preview`

1. `ariadne preview` and MCP `preview` compile and run a metric **from the active draft
   generation**. They use the governed compiler, grain and fan-out guard, deadlines and
   caps.
2. **Sources and identity.**
   - The connection is built only from source identities bound by the **current served
     approval**, and sealed with `lock_down`.
   - Every dataset source the compiled SQL consumes must resolve to such an identity.
     A draft dataset over a source that is new or changed in the draft refuses, and
     names the source.
   - A same-named table from an older destination is never used.
   - Before binding, the actual compiled SQL is authorized against the approved
     registry with the same pre-bind check validation uses (spec 0039).
3. The result carries `governed:false`, `draft_generation`, `draft_revision` and
   `served_revision`. It is never stored as an Answer Example and never cached.
4. A draft that does not validate, or a stale draft, refuses with the reasons.

### 3.7 Workspace callers (`lumio-workspace` analytics)

The workspace analytics adapter calls `AuthoringProject.approve_sources` and checks
its grant before the caller's separate data grant (`analytics.py` around lines
938–967). It also dispatches `query_records` and `define_metric` (around lines
704–744).

B1 **cuts these callers over in the same candidate**:

- the browser-reviewed source request records the source grant (§3.4.2), using the
  existing reviewer capability and one-use action;
- the per-caller data grant stays separate and is checked as before.

B2 removes the two query dispatches from the adapter in the same candidate that removes
the operations, and reports them as unsupported. B adds **no** workspace `sql`. The
existing workspace journeys are rerun as the boundary check: role separation, private
originals and curated scope (shared ADR-0028).

### 3.8 Removals in B1, and the guarantees they keep

The following are removed, along with code and tests that serve only these surfaces:

- the executables listed in §3.1;
- the two-step admission CLI (`--confirm`, `--reviewed-digest`, `--revision`,
  `--proposal`);
- `propose_sources` and `approve_sources` as separate operations, plus the
  proposal-local approval file;
- multi-proposal user workflows;
- Staging/Promotion remnants.

The guarantees these surfaces protected stay tested through `approve`:

- exact-revision and digest binding;
- atomic activation;
- source identity binding, including a changed endpoint or DSN destination needing a
  new source approval;
- validator identity;
- mapping confirmation rules.

## 4. B2: guarded ad-hoc SQL, context pack, run log

### 4.1 `ariadne sql` / MCP `sql`: supported grammar and guards

1. **Scope.** `sql` runs **one** caller-written query over the **served** approved
   sources and returns `governed:false`. It is read-only and bounded.
2. **Supported statement subset.** A statement that is not classified as supported is
   refused before binding. Supported in B2:
   - a single `SELECT` statement, including the `FROM`-first shorthand, with `WITH`
     (non-recursive CTEs), joins, subqueries, set operations, `GROUP BY`/`HAVING`,
     window functions, `QUALIFY`, `ORDER BY` and `LIMIT`.

   Refused:

   - any second statement;
   - `EXPLAIN`/`EXPLAIN ANALYZE` (`sql` has no public `EXPLAIN`; the guard
     binds internally);
   - `SHOW`, `DESCRIBE`, `SUMMARIZE` and other metadata forms (`SHOW_REF`);
   - `PIVOT`/`UNPIVOT` (`MULTI`);
   - `WITH RECURSIVE`;
   - every non-`SELECT` statement type.
3. **Guard layers.** All three must pass.
   1. **Statement guard.** `duckdb.extract_statements` must yield exactly one
      statement of type `SELECT`.
   2. **Parse-tree guard** over DuckDB's own `json_serialize_sql`. If serialization
      fails, the statement is refused.
      - The guard walks **every** node, including nested expressions and subqueries.
        Any node type outside an explicit allow-list is refused.
      - **Relations.** Each `BASE_TABLE` must be either an **explicitly qualified**
        approved relation (`catalog.schema.table`, or `schema.table` for the registry's
        file views) or a CTE that is lexically visible. Visibility follows DuckDB's
        declaration order: a CTE is visible to later siblings and the main query, never
        to its own body or earlier siblings, and names compare case-insensitively. An
        unqualified non-CTE relation is refused, which also covers the
        single-quoted-literal ambiguity. `TABLE_FUNCTION` relations are refused,
        including `read_*`, `glob`, `query`, `postgres_query` and `UNNEST` in `FROM`.
      - **Functions.** Every `FUNCTION` must name a function on an explicit allow-list
        of DuckDB built-ins (scalar, aggregate and window functions of the
        `OSSIE_SQL_2026` subset, plus the DuckDB date, string and math built-ins the
        list names). Macros, catalog-defined functions and unknown functions are
        refused. Projection `UNNEST` is refused in B2.
   3. **Locked connection.** The query runs on a connection built only from the served
      approved registry, sealed with `lock_down`. Before the lock, the session holds no
      secrets beyond the registry's storage profiles. The lock is **defense in depth
      only**; containment is the job of guards 1 and 2.
4. **Authorization and execution use the same resolution.** After guards 1 and 2, every
   qualified relation is resolved against the session's catalog. It must resolve to
   exactly the registry entry the guard accepted. The statement then runs as checked;
   it is never rewritten after authorization.
5. **Budgets.** The deadline covers parse, guard, bind and fetch. Results use the
   existing row and byte caps. **When a cap is exhausted, the call returns the existing
   typed refusal**, not a truncated success, and it does not count the full size.
6. **Result.** The result carries:
   - `governed:false`;
   - `served_revision`;
   - `tables` (the approved relations read);
   - `policies` (§4.2);
   - `warnings` (§4.3);
   - the rows within caps.

### 4.2 Policy and caveat disclosure for `sql`

1. `sql` is a new **operation ID** in the integrated capability table, with a new
   `support_revision` 5 that adds `sql` and `context` and removes `define_metric` and
   `query_records`.
   - Older admitted releases keep their recorded operations.
   - An existing Policy Binding naming `define_metric`/`query_records` is **not**
     silently moved. `approve` on a revision-5 selector refuses bindings that name
     removed operations, and the message names them.
   - **Upgrading an existing revision-4 project to the B2 build:**
     - Its served release was admitted under the old execution build identity.
       `verify_release` checks that identity, so the new build refuses to serve that
       release, as it does today for any build change.
     - `ariadne status` names the cause.
     - The fix is the normal path: `ariadne migrate` (when needed), then a draft that
       moves the selector to `support_revision` 5 and removes or replaces bindings that
       name removed operations, then `validate`, then `approve`.
     - Calls to the removed operations report `operation_removed`, naming `sql` as the
       replacement. They are never silently routed to `sql`.
     - Nothing runs a revision-4 release on the new build.
2. For each table read, `sql` discloses the Policies bound, under the served release,
   to the dataset or resource subjects whose **physical source identity** equals that
   table's resource identity. These are disclosed as **advisory**.
   - If a table backs no dataset, or several datasets with different Policies, the
     disclosure says `policy_applicability: unknown` and lists the candidates.
   - `sql` never claims a filter enforces a Policy. No `enforced` label appears for
     `sql` results.
3. Visibility rules and row boundaries that are independently enforced elsewhere
   (workspace audience) are not weakened. Inside a workspace, `sql` is available only
   to a caller whose existing analytics data grant covers every table read.

### 4.3 Warnings (the result is still returned)

| Class | Trigger |
|---|---|
| `undeclared_join` | A join between approved relations not declared in the served model or `graph.yml` |
| `fanout` | A join along a declared one-to-many relationship whose many side feeds an aggregate of the one side |
| `grain_unknown` | An aggregate over a join whose grain cannot be determined from declared relationships |
| `policy_unknown` | §4.2.2 |

An aggregate over an undeclared join returns its rows with both `undeclared_join` and
`grain_unknown`. A join along a declared one-to-many relationship into an aggregate
returns `fanout`. Both are distinct from the cap refusal.

Each warning names the relation or relationship. Cap exhaustion is a refusal (§4.1.5),
not a warning.

### 4.4 `ariadne context` / MCP `context`

1. Returns a bounded pack (default 16 000 characters) with truthful omission
   disclosure. It contains:
   - the relevant datasets and columns with their descriptions;
   - the **already published** observed values, with their visibility, observation
     time and omissions;
   - relationships with cardinality;
   - filter rules and required Policies, as advisory;
   - approved metrics that nearly match, with their identities;
   - the most relevant Answer Examples with their SQL.
2. It reads only the served release and its published knowledge. It never profiles or
   opens a source to fill a gap.
3. It carries the `served_revision` it used. `context` and a later `sql` may use
   different releases if an approval happened in between; each result states its own
   release.

### 4.5 Run log: normalized, without values

1. These operations append one record to `.ariadne/runs.duckdb` (mode 0600, git-ignored,
   outside every registry and therefore unreadable by `sql`): `query`, `detail`,
   `preview`, `sql` and `context`, including refusals.
2. **Stored fields:**
   - time and operation;
   - served and draft revision;
   - the relations read;
   - outcome (`ok`, a refusal class, or `error` with a classified error code);
   - warning classes, row count and duration.
3. **Refusals never store caller text,** whether the refusal happens before or after
   parsing. A refusal record stores only the refusal class and the relation names that
   the guard resolved.

   **A successful query stores normalized SQL only when it is safe to keep:**
   - the text is DuckDB's normalized form;
   - literals are replaced by `?`;
   - comments are removed;
   - every alias and CTE name is replaced by a positional placeholder (`a1`, `c1`, …).

   Only approved relation names and allow-listed function names survive verbatim. If
   this normalization cannot be produced, no text is stored.
4. **What is never stored:**
   - the question text (only its length and a SHA-256);
   - raw caller text;
   - literal values;
   - result values;
   - engine error messages (only classified error codes);
   - credentials.
5. **Writing and retention.**
   - Writes are serialized with a file lock with a short timeout. If the log cannot be
     written, the query result is still returned and carries `run_log: unavailable`.
   - Retention is 90 days (`run_log.retention_days` in the private profile). Old rows
     are deleted on the first write of each day. Deletion is not a secure-erase promise.
   - `run_log.enabled: false` stops all writes.
6. The log is runtime state. Nothing reads it to change retrieval, models or examples.

### 4.6 Removals in B2

The following are removed:

- `define_metric`, `query_records`, their CLI and MCP surfaces;
- the `adhoc.*` entries of the existing-check catalog;
- Ad-hoc Metric staging and the record-query paths.

Their safety tests (source containment, caps, deadline, redaction) are migrated to
`sql`.

## 5. Invariants

1. `governed:true` appears only for `query`/`detail` on approved definitions of the
   served release.
2. `preview`, `sql` and `context` always return `governed:false`.
3. No shipped agent interface can approve, discard, grant a source or confirm a
   mapping.
4. No source is read before the source approval that grants it. A failed approval
   creates no grant. A source grant never changes the served release or repoints a
   served calculation.
5. Every connection over approved sources outside the governed query is locked.
   - Authoring connections (validation, preview, profiling, inspection) are built only
     from granted identities: the served release's bindings plus the source grants.
   - `sql` and `context` use only the served release's bindings.
6. The governed query keeps its compiler-only SQL path and its existing guards.
7. Credentials, literal values and engine messages never reach the run log. Redaction
   holds in every new message.
8. The served state changes only through a calculation `approve`. Activation is atomic,
   and a failure leaves the previous state and grants intact.

## 6. Acceptance examples

### B1

1. **Owner path.** In a fresh directory the §1 owner path succeeds:
   - `init`, `add`, then a sources-only `approve` (TTY "yes");
   - `draft edit model.yaml`, `validate`, `preview`;
   - `approve`, then `query` returns `governed:true`.

   No step takes an ID, revision, digest, namespace or selector.
2. **Source-approval failures.**
   - A source approval that fails its live check after "yes" leaves the served state
     unchanged and creates no grant. `profile` and `authoring_inputs` then refuse that
     source.
   - A refused prompt also leaves no grant.
3. **Mixed drafts.** `approve` of a draft that adds a source **and** a model refuses and
   asks the user to approve the source first.
4. **Changed source identity.** Take a source that an admitted metric uses and change
   its endpoint or DSN destination.
   - It requires a new source approval. Until then, preview and profiling refuse the
     new identity.
   - After the source approval, with the environment variables now pointing at B,
     governed `query` of that metric **refuses** with a message naming the source and
     the pending calculation approval. It never returns B's data. `preview` reads B.
   - Only after a calculation approval does `query` use the new identity and answer.
   - A test proves this with distinguishable A and B data through the real CLI
     (`ariadne query`) and the real `ariadne approve` path.
   - `add` refuses an inline Postgres DSN with credentials and names the
     `connection_env` form.
   - A sources-only approval leaves the served release digest byte-identical.
5. **No TTY.** `approve` without a TTY refuses and changes nothing. MCP lists no
   approve, discard, source-grant or mapping-confirmation tool. The removed executables
   are absent from the installed wheel.
6. **First-write race.** Two concurrent first writes (CLI `add` and MCP edit) yield one
   draft. The loser refuses as stale.
7. **Edit during the prompt.** An edit between the display and "yes" makes activation
   refuse, and nothing changes.
8. **Rebase.** After the served state advances, `preview` refuses as stale.
   - A clean `draft rebase` succeeds and invalidates validation.
   - A conflicting rebase leaves the draft exactly as before and names the files.
   - A discarded draft is never resurrected.
9. **Preview isolation.** `preview` of an edited metric returns `governed:false` with
   the draft revision, while `query` keeps serving the old definition. Preview over a
   dataset whose source is new in the draft refuses.
10. **Migrated admission guarantees** hold through `approve`:
    - exact-revision binding;
    - stale or edited revision refusal;
    - the failed-activation rollback;
    - the validator-identity change;
    - mapping confirmation, including a hypothesis being unconfirmable.
11. **`init` in an existing repository** with unrelated staged and unstaged work commits
    only its own files and leaves the rest untouched. A conflicting existing file
    refuses.
11a. **Workspace cutover.** The existing workspace analytics journeys pass:
    - a source request goes through browser review and grants the source;
    - the separate caller data grant is still required;
    - role separation and private originals are unchanged.

    After B2, the workspace dispatch of the removed operations reports
    `operation_removed`.

### B2

12. **`sql` refusals.** `ariadne sql` refuses each of the following before binding:
    - `read_csv('~/.env')`;
    - a single-quoted path relation;
    - `postgres_query(…)`;
    - `glob(…)`;
    - projection `UNNEST`;
    - a catalog macro call;
    - `SHOW`/`DESCRIBE`/`SUMMARIZE`;
    - `PIVOT`;
    - `WITH RECURSIVE`;
    - `EXPLAIN`/`EXPLAIN ANALYZE`;
    - `COPY`, `ATTACH`, `SET`, `CREATE SECRET`;
    - a second statement;
    - an unqualified non-CTE table;
    - a CTE referencing itself or a later sibling;
    - a table outside the registry.

    Each refusal is logged with its class and without text.
13. **Supported queries answer.** A `FROM`-first query and a window-function cohort
    query over approved sources answer with `governed:false`, `tables` and advisory
    `policies`.
14. **Warnings and caps.**
    - A join that fans a declared one-to-many relationship into a `SUM` returns rows
      plus a `fanout` warning naming the relationship.
    - An aggregate over an undeclared join returns rows plus `undeclared_join` and
      `grain_unknown`.
    - An exhausted row cap returns the typed refusal, not rows.
15. **Policy applicability.** A table backing two datasets with different Policies
    returns `policy_applicability: unknown` with both candidates. No result is labeled
    as enforced.
16. **Live S3/Postgres (CI S3 job, intact guards).** The following are refused, each by
    the named guard:

    | Case | Refused by |
    |---|---|
    | G1 (`..` traversal, an outside bucket or prefix) | the relation guard |
    | G3 (`postgres_query`) | the function/relation guard |
    | G4 and G5 | the statement guard |

    A separate local test shows the lock refuses a supported-shape read of a file
    outside approved paths when the relation guard is bypassed by a scratch fault.
    S3 containment is **not** claimed from the lock.
17. **Run-log privacy.** None of the following inputs leaves a DSN, password, name,
    alias, comment or literal in `.ariadne/runs.duckdb`:
    - a refused `sql` before parsing, with an inline DSN and password;
    - a refused `sql` after parsing, for example an unapproved table, with a personal
      name in a column alias and in a comment;
    - a successful `sql` with a personal name in an alias, a CTE name and a comment;
    - a `context` question with a personal name.

    The successful query stores normalized SQL with `?`, `a1`/`c1` placeholders and no
    comments. The file mode is 0600. When the log is unavailable, the query result is
    still returned with `run_log: unavailable`.
18. **Context pack.** `ariadne context` returns a pack within budget with the relevant
    dataset, relationship, observed values marked with their age, and an Answer Example
    with SQL. Omissions are disclosed. No source is opened.
19. **Revision-4 upgrade.** An existing revision-4 project with a Policy Binding on
    `define_metric`, after installing the B2 build:
    - `status` names the build-identity refusal, and governed queries refuse with it;
    - the removed operations report `operation_removed`;
    - a draft moving to `support_revision` 5 that still binds `define_metric` is refused
      by `approve`, with the name;
    - after the binding is removed, `validate` and `approve` admit a revision-5 release,
      and governed queries and `sql` work.

## 7. Artifact reconciliation

- **New ADRs (Ariadne):**
  - **ADR-0029 "Single approval with a source-first gate; consent convention"** replaces
    the gate structure of ADR-0010 (separate source approval), ADR-0016 and ADR-0024
    (multi-proposal CLI) where they conflict, and the two-step CLI part of ADR-0026.
    The Bound Release semantics of ADR-0026 and shared ADR-0029 are **unchanged** in B;
    B3 amends them.
  - **ADR-0030 "Guarded ad-hoc SQL over a supported subset"** supersedes ADR-0005 and
    ADR-0019. It amends spec 0032's operation table through `support_revision` 5.
- **Superseded clauses** (one-line headers on the affected sections, with no rewriting
  of history):
  - umbrella 0037 §1 "four commands" and §4 B's first-source preview-before-approval
    (replaced by §3.4 here);
  - umbrella 0037 §4 B run log: "stores … question" and "SQL" (replaced by §4.5
    here);
  - 0037 §4 B "tier K" (moved to the B3 spec);
  - spec 0039 §7.1 "migrate opens its own proposal" (now the active draft);
  - specs 0009, 0014, 0027 and 0032 in their CLI, ad-hoc and record parts;
  - shared spec 0035 only where the separate source-approval step is named, keeping its
    exact binding and retention guarantees.
- **CONTEXT.md (Ariadne):**
  - Add: Draft, Draft Generation, Source Approval (redefined as the first approval of a
    source identity), Calculation Approval, Preview Query, Ad-hoc Query, Context Pack,
    Run Log.
  - Update: Authoring Proposal and Candidate Revision (now internal to the draft), Git
    Review Admission (now "Approval").
  - Remove: Ad-hoc Metric, Ad-hoc Record Query, Proposal, Staging, Promotion.
- **Lumio:** no change.

## 8. Delivery and verification

- B1 and B2 are separate candidates. Each has its own plan, isolated worktree,
  independent review and full CI gate, and each lands before the next one starts. B2
  depends on B1.
- Live guard checks extend the existing `onboarding-s3-compat-journey` CI job (SeaweedFS)
  and add a Postgres service there.
- Sub-agents run as **Herdr panes** in the project's tab (owner instruction,
  2026-11-22).

## 9. Capture checkpoint

- **Vocabulary:** see §7.
- **Decisions:** ADR-0029 and ADR-0030.
- **Behavior:** §3–§5, acceptance examples in §6.
- **Uncertainty:** none blocking. The function allow-list for §4.1.3.2 is written
  out in B2's plan, as a data table with one test per class.

Planning Contract version 1; installed provenance `unknown`.
