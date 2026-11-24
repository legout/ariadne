# Plan 0040-B1: one CLI, one active draft, source-first approval, preview

Status: **owner-approved with spec 0040 r3**, 2026-11-22 ("freigabe"). Source:
[spec 0040 r3](../specs/2026-11-22-0040-one-cli-simple-governance.md) §§1, 3, 5, 6 (B1:
AC1–AC11a), 7, 8. This plan covers B1 only. B2 gets its own plan after B1 lands.
Target integration and publication still need the owner. The 2026-11-24 scoped
preview decision updates T7 and its validation below; this is not a new dispatch
or integration grant.

## Execution model

- **Mode:** supervised, light. One sequential writer works in an isolated worktree
  under `~/.local/state/worktrees/`.
- **Base:** origin/main at dispatch, including the spec 0040 commits.
- **Host:** herdr-core.
  - **Children run as Herdr panes in the project's tab** (owner instruction): create
    them with `herdr pane split`, start Pi with `herdr pane run`, and report back with
    `hc send <parent>`.
  - Worker: `claude-code/claude-sonnet-5-5:high`.
  - Reviewer: `openai-codex/gpt-6.2-sol:high`.
- **Resource hygiene:** RAM and `/tmp` are tight.
  - Run pytest serially in focused runs, with `--basetemp` under `/tmp/b1bt-*`, and
    delete it afterwards.
  - Build pair venvs one at a time and delete each one after use.
- **Commits:** one commit per task, or more where a task needs them.
- **Reviews:**
  - an independent review after T6, the contract-defining state and approval core;
  - a review of the whole candidate at V.
  - Each review gets one fix pass and one delta recheck. Anything still unresolved goes
    to the owner.

## Tasks

### T1 — Draft slot and project-wide compare-and-set (`new-test`)

Source: spec §3.3; AC6, AC7, AC8.

Add `ariadne/draft.py`:

- `.ariadne/draft.json` holds `generation`, `proposal`, `candidate_revision` and
  `base_served_revision`, all under the project lock;
- `open_or_create` uses compare-and-set on "no slot";
- every mutation carries the expected generation and candidate revision;
- `discard` retires the slot and moves the branch to `ariadne/discarded/<generation>`;
- `rebase` performs a real rebase in the proposal worktree; on conflict it aborts and
  leaves the draft exactly as it was;
- staleness is detected against the served revision.

Route these existing proposal operations through the slot:

- `start`, `edit`, `edit_pages_batch`, `validate` (finalize), `reconcile`;
- `migrate`, whose spec 0039 §7.1 conflict is superseded here.

Tests:

- the first-write race;
- a stale generation refuses;
- discard is not resurrected by a later write;
- a clean rebase invalidates validation;
- a conflicting rebase leaves the draft unchanged.

### T2 — Source grants replace proposal-local source approval (`new-test` + `existing-check`)

Source: spec §3.4.2 and §3.4.4; AC2, AC4.

Add `.ariadne/source_grants.json`: append-only, under the project lock. Each entry
holds:

- the exact credential-free identity, the same one `resolved_digest` uses today;
- `binding` and `postgres_binding`;
- attribution, time and digest.

The effective grant set is the served release's bound identities plus the grants.
Repoint every consumer of `authoring_sources._effective_grant` and the proposal-local
approval file to it:

- `authoring.inputs`, `refresh_schema`, `inspect_mapping`;
- contract observation;
- `profile`.

Delete the proposal-local approval file and `approve_sources` as an operation.
`add` refuses an inline Postgres DSN that contains credentials.

Tests:

- a grant enables a bounded read;
- a missing grant refuses;
- a changed endpoint needs a new grant;
- the inline DSN refusal.

### T3 — Approval core (`new-test` + `existing-check`)

Source: spec §3.4.1–3 and §3.4.5, §3.5.1; AC1, AC2, AC3, AC4, AC7, AC10.

Add `ariadne/approve.py`:

**Classification.** A draft is either a source approval (only source declarations and
storage profiles, at least one new or changed identity) or a calculation approval.
A mixed draft is refused.

**Source approval:**

1. Run the offline checks.
2. Display the result and prompt on the TTY.
3. Recheck the identity.
4. Run the live checks inside the transaction.
5. Append the grant.
6. Consume the generation into the approved source baseline commit.

On any failure no grant is written. The served release stays byte-identical.

**Calculation approval:**

1. Validate, reusing a matching earlier validation.
2. Build the summary (reuse `admission.admission_review`/`overall_review`).
3. Prompt on the TTY.
4. Call `admit_revision`, pinned to the displayed generation, revision, digest and
   served base.

Admission validates only against granted identities.

**Other rules:**

- `--confirm-mapping` keeps today's rules.
- Without a TTY on stdin and stdout the command refuses.
- No skip flag exists.

Migrate the existing admission tests: exact revision, stale or edited revision, failed
activation, validator identity, mapping confirmation.

Add new tests:

- an edit during the prompt;
- a failed live check;
- a refused prompt;
- a mixed draft;
- a changed endpoint: `query` still uses the old identity until a calculation approval;
- a sources-only approval leaves the release digest byte-identical.

### T4 — `ariadne init` (`new-test`)

Source: spec §3.2; AC1, AC11.

`init` creates the Git repository and, after one prompt, a local identity. It then
creates:

- the namespace;
- the private profile (mode 0600, with destination, Visibility Scope and run-log
  defaults);
- the selector at the highest `support_revision`;
- the native Lumio KB.

It makes one commit that contains only its own files. A re-run is a no-op. A
conflicting existing file is refused.

Tests:

- an empty directory;
- an existing repository with unrelated staged and unstaged work;
- a conflicting file;
- the re-run no-op.

### T5 — One CLI (`existing-check` + `new-test` for removals)

Source: spec §3.1; AC5.

- `cli.py` provides the exhaustive command table of spec §3.1.2. It reuses the existing
  implementations for `query`, `detail`, discovery, `serve`, `skill`, `profile`,
  `migrate`, `validate` and `diff`.
- `pyproject.toml` keeps only `ariadne`.
- Delete `authoring_cli.py`, the `main`s of `admission.py`, `validate.py`, `init.py`,
  `setup.py`, `skill.py` and `profiler.py`, `review.py`, and the `serve` entry-point
  variants. Keep the library functions that are still used.
- Text output by default, JSON with `--json`. `serve` is exempt (spec §3.1.2, owner
  decision 2026-11-23).
- Update the walkthrough script (`tests/setup_wheel_walkthrough.py`) to the new flow.

Test: the installed wheel exposes only `ariadne`, and every subcommand's `--help` works.

### T6 — MCP surface (`existing-check` + `new-test`)

Source: spec §3.1.3; AC5.

- `authoring_edit_proposal` acts on the active draft and accepts no proposal or base
  IDs.
- `authoring_propose_sources` is removed; a typed source edit goes through
  `authoring_edit_proposal`.
- Add `draft_status` and `preview`, the latter backed by T7.
- No approve, discard, grant or mapping-confirmation tool exists.
- Update the packaged skill text: agents never run `approve`; the new commands are
  listed.

Test: the tool list on every toolset contains none of the forbidden tools.

**Review checkpoint R1** runs after T6 on the contract-defining state (T1–T6) with an
independent reviewer. One fix pass and one delta recheck.

### T7 — `preview` (`new-test`)

Source: spec §3.6; AC9.

Compile from the active draft generation. Build the locked connection from the
exact draft bindings, only for granted identities, including completed grants not
in the served release. An ungranted, mismatched or pending identity refuses before
reading it; never substitute an older same-named binding. Apply the pre-bind
authorization of the compiled SQL (spec 0039). The result carries `governed:false`,
`draft_generation`, `draft_revision` and `served_revision`. A stale or invalid draft
is refused.

Tests:

- preview of an edited metric while `query` still serves the old definition;
- a new-source dataset refuses before a grant and previews after the exact grant,
  before calculation approval (AC1 and AC9);
- a stale draft is refused.

### T8 — Workspace cutover (`existing-check`)

Source: spec §3.7; AC11a.

In `lumio-workspace` `analytics.py`, the browser-reviewed source request records the
source grant through T2/T3's library call. That call is not agent-reachable: it sits
behind the existing reviewer capability and the one-use action. The per-caller data
grant stays separate and unchanged. The `query_records`/`define_metric` dispatch stays
until B2.

Rerun the existing workspace analytics and review journeys, which check role
separation and private originals.

### T9 — Artifacts (`no-new-test`)

Source: spec §7.

- ADR-0029 "Single approval with a source-first gate; consent convention" (Ariadne
  ADR, accepted with the spec).
- Superseded-clause headers: umbrella 0037 §1/§4 B as listed; spec 0039 §7.1;
  specs 0009/0027 CLI parts; spec 0035, only the separate source-approval step.
- CONTEXT.md additions and updates for B1: Draft, Draft Generation, Source Approval
  (redefined), Source Grant, Calculation Approval, Preview Query; update Authoring
  Proposal, Candidate Revision and Git Review Admission (now "Approval"); remove
  Proposal, Staging and Promotion. B2's terms come with B2.

### V — Candidate verification

Source: AC1–AC11a.

On the final tree:

- the Core CI selection (pair-installed) on 3.12 and 3.14;
- Lumio native `-n 4` (workspace changed);
- root `-n 4`;
- wheel build, install and the new walkthrough;
- `ruff check`;
- the AC4 live A/B journey: a served release reads A; the source endpoint changes to B
  and is granted through the real `ariadne approve`; `ariadne query` refuses by name,
  while a validated draft preview reads B as `governed:false`. Governed query reads B
  only after a calculation approval. It runs against a live Postgres source
  in CI, not only offline (owner decision 2026-11-23: R1 accepts the offline proof of
  the named refusal; this live leg must pass before V is accepted).
- the strict interruption oracle for the stdio regression test (spec 0040 §3.4.2.5): a
  signal told apart as late, missing, or crossing the close of the cleanup window, and
  the test launcher's own handler observation restored on every unwind. R1 closes with
  the reduced test (a real interrupt in the window leaves a consistent state, and a
  later `draft status` reports the outcome); this stricter proof is settled here
  (owner decision 2026-11-24).
- the remaining witness limits of that stdio regression test (owner decision
  2026-11-24: R1 is closed on the verified product code after twenty fix-first rounds,
  the last eight test-only, with the test as it stands at the R1 result; no further R1
  round): (a) the second `KeyboardInterrupt` is accepted when its traceback holds the
  call frame and the Runner handler frame in any order, so a handler called by hand
  from an audit hook counts, and a record's signal attempt is not checked against its
  index; (b) the evidence stamps precede the writes and the deciding snapshot is taken
  once the expected count is present, so a record stamped on time but written late
  counts and a later event of the same attempt is not seen. One negative control can
  fail spuriously under scheduling jitter. Settle these here with the strict oracle.

Run the AC1 owner path end to end against the installed wheel in a temporary
directory, with the TTY simulated through a pty.

Then the independent candidate review (gpt-6.2-sol), with one fix pass and one delta
recheck. Push the candidate branch and wait for full CI. Pause before integration.

## Order

T1 → T2 → T3 → T4 → T5 → T6 → **R1** → T7 → T8 → T9 → V.

## Coverage

| AC | Tasks |
|---|---|
| AC1 | T3, T4, T5, V |
| AC2 | T2, T3 |
| AC3 | T3 |
| AC4 | T2, T3 |
| AC5 | T5, T6 |
| AC6 | T1 |
| AC7 | T1, T3 |
| AC8 | T1 |
| AC9 | T7 |
| AC10 | T3 |
| AC11 | T4 |
| AC11a | T8 |

Planning Contract version 1; installed provenance `unknown`.
