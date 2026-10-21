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

## Repository contexts

This repository hosts two independent products. `CONTEXT.md` is the Ariadne
vocabulary; `project/lumio/CONTEXT.md` is the Lumio vocabulary (ownership
unchanged; see `CONTEXT-MAP.md`). Scoped package instructions live in
`packages/lumio-wiki/AGENTS.md` and `packages/lumio-lancedb/AGENTS.md`;
Lumio records keep their original IDs under `project/lumio/`, where
`AGENTS.imported.md` is a preserved historical reference, not active
guidance.
