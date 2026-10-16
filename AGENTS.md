# AGENTS.md

## Project Context

This repository contains the open-source Lumio foundation: the portable,
model-free Knowledge Base SDK (`packages/lumio-wiki`) and the optional LanceDB
enhanced-retrieval adapter (`packages/lumio-lancedb`). The deployable Lumio web
application lives in a separate private repository and consumes these published
wheels (ADR-0025).

Before implementation work, read:

- `CONTEXT.md` — the project's ubiquitous language (glossary).
- `project/specs/0002-core-sdk.md` — the Core SDK PRD.
- `project/adr/` — architectural decisions that govern implementation choices.
  ADR-0010 defines the workspace and packaging; ADR-0025 records the
  repository split.

## Validation

- Run focused tests serially while developing: `uv run pytest -q <test paths>`.
- Run the full suite with four workers: `uv run pytest -q -n 4`.
- Do not use `-n auto`; a fixed worker count keeps local and CI resource use predictable.

## License

Contributions are licensed Apache-2.0 (see LICENSE).

## Approved Git-authoring transition

For issue #1 implementation, owner-approved
[specification 0008 r2](project/specs/2026-10-15-0008-git-native-knowledge-authoring.md)
and [ADR-0029](project/adr/0029-git-native-knowledge-authoring.md) replace the
proposal-based target contract. Planning/execution and target integration retain
their separate gates. The generated operating section below describes the
legacy installed CLI and configured shared KB, not a requirement to keep
proposal persistence in the replacement. Use disposable test KBs for new Git
flows; do not migrate, edit, or publish the configured shared KB under this
implementation task. Refresh generated operating guidance with the implemented
replacement, never prematurely on the target branch. Owner scope amendment
2026-10-16 excludes the private app entirely: execute the public foundation
only, with `lumio-lancedb` edits when actually necessary. The known private
consumer incompatibility remains a later integration/release decision, not a
private-work prerequisite for the isolated public candidate.

<!-- lumio-wiki-kb -->
## Lumio Knowledge Base

This project uses a Lumio Knowledge Base for domain knowledge. The host coding
agent IS the default Distiller (no model provider needed for base ingestion).

**KB path:** `/home/volker/coding/lumio/.wiki` (also in `.env` as `LUMIO_KB_PATH`; the CLI reads it
automatically when no `<kb>` argument is given).

### Retrieval ladder (cheapest-first, stop when you have Evidence)

0. `lumio-wiki hot` — Maintainer-pinned entry pages. Read first.
1. `lumio-wiki index [dir]` — generated Navigation Index (all pages by directory).
2. `lumio-wiki search "<query>"` — zero-index lexical search (no external index).
3. `lumio-wiki page "<title>"` — read a page to confirm and cite the exact passage.
4. `lumio-wiki related "<title>" --scope discovery` — related pages (canonical + extracted).
5. `lumio-wiki paths "<src>" "<dst>"` — shortest directed path between two titles.

### Ingest (you are the Distiller)

1. Author a Compiled Page (YAML frontmatter + Markdown body) that declares the
   source identity in `sources[].id`.
2. `lumio-wiki ingest <original-source> --compiled-page <page.md> --source-id <id>`
   — bind the ORIGINAL raw source to your authored page under one stable
   identity and stage a single reviewable Ingest Proposal. No `[documents]`
   extra required (the converter name is derived from routing without running
   it). Plain `lumio-wiki ingest <file>` stays available for text/Markdown
   passthrough but does NOT establish a Source identity.
3. `lumio-wiki proposal list` → `proposal inspect <id>` → `proposal validate <id>`.
4. `lumio-wiki publish <id>` (or `lumio-wiki discard <id>`).

### Maintenance (you are the Maintainer)

- `lumio-wiki lint` — read-only cross-page QA: validation, graph health, and
  canonical/discovery structural diagnostics with scope disclosure. Exit 1 if invalid.
- `lumio-wiki cross-link` — missing-link candidates ranked by Discovery Graph
  impact. Add `--stage` to stage reviewable repair proposals (never direct-writes).
- `lumio-wiki dream` — the Dream Cycle: read-only reflection (validation +
  health + structure + ranked candidates). Add `--stage [--limit N]` to stage
  the top repairs as ordinary Ingest Proposals for review. Add opt-in `--semantic`
  with the `[llm]` extra for semantic findings; it remains proposal-first.

### Guardrails

- **Cite or refuse.** Every domain claim cites a Compiled Page (title + path +
  passage). Unsupported claims return "not covered by this knowledge base."
- **Connectivity is not support.** Graph reachability selects pages to inspect;
  it never manufactures Evidence.
- **Proposal-first.** Validation always runs before publish. Never write `.md`
  files directly to the KB root.

### Diagnostics

- `lumio-wiki doctor` — version, detected extras, skill location.
- `lumio-wiki health` — page counts, validation, Discovery Graph health.
- `lumio-wiki status [<kb> | --json]` — effective configuration and retrieval state.
- `lumio-wiki validate` — exit 0 if valid, 1 otherwise.
- `lumio-wiki lint` — full QA report (superset of validate + structural diagnostics).
<!-- pi-implementation-orchestrator:start -->
## Agent workflow

- Follow the installed `orchestrate-implementation` skill for validation obligations (`new-test`, `existing-check`, `no-new-test`), review timing, committed-result handoffs, and patch-only recovery. Load it before dispatch; do not maintain a second execution procedure here.
- Plans and tickets reference exact feature sources; this file defines stable repository-wide scope.
- Scoped authority: glossaries own terminology; ADRs own accepted architectural constraints; specifications own behavior; plans/tickets own execution decomposition. No scope silently overrides another; reconcile owner decisions into the affected artifacts before dependent work proceeds.
- Stop before implementation when authoritative sources conflict.

### Review ground rules

- Priority: agreed feature, then correctness, then proven risk. Written conventions are binding; taste never blocks. Name the applicable instruction, style, lint, or contract source; if none exists, say so rather than inventing conventions.
- Findings need a named requirement or written rule, a problem this change caused or worsened, reachability through real callers/inputs/environment, material impact, and a proportionate response.
- Security requires a touched boundary (untrusted/external input, credentials, auth, dependency changes), named asset, realistic attacker, and actual attack path. Stories needing stolen secrets, broken TLS, malicious admins, or generic hardening are not findings. No boundary touched: `security: n/a`; missing security facts: `unverified`, never invent a threat model. Trusted internal callers and the user's own local files are not hostile by default.
- Test requests are findings: name a real scenario or drop them. Coverage percentage is not a reason.
- Generated tests are findings when they mirror the implementation's structure, over-mock, relax assertions to force green, or hardcode expectations copied from implementation output; expected values come from the spec, acceptance criteria, or an independent oracle — never from reading the code under test.
- Disposition before repair: parent rejects failed gates in one line, authorizes small in-scope fixes, or hands large/out-of-scope fixes to the human. Reviewers never start fixes or re-reviews.
- Reviews end when criteria, real risks, and written rules are covered: `pass or fix-first`, then stop. One fix pass, one delta recheck; unresolved findings go to the human, never round three. Candidate review checks integration effects, not settled findings again.
- Paste the full reviewer contract from `orchestrate-implementation` into every fresh reviewer prompt, with criteria, conventions, and real-use context; file links alone do not deliver it.
- After each task: restate it, compare the result, choose `accept / fix / hand back / ask`. Extra ideas get one line, not code. Smallest safe change; one behavior and, for `new-test`, one focused test with independently derived expectations — failing-first only for bug repros and refactor pinning. Dependencies and abstractions need a job today. No extra ledgers or sign-off artifacts.

### Routing and authority

- Read `project/agents/artifacts.md` for the project artifact mapping and load the `planning-contract` skill for artifact classification and planning handoffs; read `project/agents/issue-tracker.md` and `project/agents/domain.md` when their scope applies. Preserve established project conventions.
- Use `shape-design` for unresolved behavior/design choices, `write-implementation-plan` for approved multi-step work, and `orchestrate-implementation` to execute approved work. Do not turn a trivial edit into a planning exercise.
- Default orchestrated execution to `supervised`: prepare and review an isolated candidate, then pause before target integration. Explicit owner restrictions still bind; execution grants no integration or publication authority.
- Use Pi for every child role. Follow the skill's host selection: explicit/configured host selection wins, otherwise use the verified current host (native `pi-subagents`, `herdr-pane`, Paseo’s Pi provider, or T3’s Pi driver). T3 children remain read-only without supported isolated workspace binding. Native Pi dispatch uses executable `worker`/read-only `reviewer` profiles, not external-runner aliases.
- Use `${XDG_STATE_HOME:-$HOME/.local/state}/worktrees/` for new worktrees, with allocator-supported subdirectories. Preserve existing worktrees and allocator configuration; approve incompatible host settings separately before dispatch.
- Follow the selected adapter's shared-root and exact model/thinking preflight; record the resolved host and roles in existing run state. Keep one writer per isolated registered worktree. Use host lifecycle controls; intercom is optional messaging, not workspace placement or lifecycle authority. Do not silently switch hosts or runtimes. Named persistent peers remain read-only advisors.
- Use `systematic-debugging` for unexpected failures and `verification-before-completion` before success claims; match evidence to the exact change and report skipped checks.
- Use `merge-worktree` for target integration and `make-release` for releases. Local integration does not authorize pushing; opening a PR does not authorize merging; release or publication requires its own approved plan.
- Stop on conflicting authoritative sources, unclear ownership, failed required gates, or missing required tooling. Never silently switch execution modes to bypass a blocker.

### Documentation map

- `CONTEXT.md`: canonical domain vocabulary for the whole repository.
- `project/adr/`: accepted architecture decisions.
- `project/agents/`: workflow, tracker, and artifact-map configuration.
- `project/specs/` or the configured tracker: feature behavior and acceptance.
- implementation plans/tickets: execution entry points and explicit source references.
<!-- pi-implementation-orchestrator:end -->
