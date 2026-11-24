# Agent software factory

One **foreman** agent session runs this project. It triages GitHub issues, routes each one to a lane, starts **worker** agent sessions on its host (Herdr, Paseo, or BB), checks their results, and merges the work. The foreman follows the `foreman` skill. Workers follow the shared rules below and the section for their role.

## Project

- Repository: `legout/ariadne`. Default branch: `main`.
- Setup: `uv sync` (all workspace members; see `CONTRIBUTING.md`).
- Focused test (serial, never `-n auto`; RAM and `/tmp` are tight):
  - Ariadne Core: `cd products/ariadne/packages/ariadne-data && PYTHONPATH=../../../.. uv run pytest -q --basetemp=/tmp/<issue>-bt tests/<file>.py` (tests import `integration`; CI runs them pair-installed), then delete the basetemp.
  - Lumio: `cd products/lumio && uv run pytest -q packages/<member>/tests/<file>.py`.
  - Shared: `uv run pytest -q tests/<file>.py` from the root.
  - Lint the touched area with its own config: `uv run ruff check .` in the root, `products/lumio`, or `products/ariadne/packages/ariadne-data` (with `--extra dev`).
- Full gate (CI): the `CI` workflow (`.github/workflows/ci.yml`): root, Lumio native and Core pair-installed suites plus ruff on Python 3.12 and 3.14. Workers do not run it locally; the PR run is the gate. `docs` deploys Pages on `main` only and is not a PR gate.
- Sources of truth: `products/ariadne/CONTEXT.md` and `products/lumio/CONTEXT.md` (see `CONTEXT-MAP.md`); ADRs in `project/adr/`, `products/ariadne/project/adr/`, `products/lumio/project/adr/`; specs and plans in `project/specs/`, `project/plans/` and `products/<product>/project/`; the artifact map in `project/agents/artifacts.md`. If they conflict with each other or with an issue, stop and ask the foreman.

## Authority (owner grant)

The foreman may do the following without asking:

- create, label, comment on, and close issues;
- create worktrees and branches, push `issue/*` branches, and open PRs;
- squash-merge a PR into `main` once its lane gate passes and CI is green;
- start, steer, and stop the worker sessions it started.

These always need the owner:

- a release, publish, deploy, or tag;
- a force-push to `main`, or any rewrite of its history;
- a change to repository settings, secrets, or CI permissions;
- a new runtime dependency;
- deleting data or unmerged work;
- anything that no spec or ADR covers;
- a `core-v*` or `lumio-v*` tag (it publishes to PyPI).

## GitHub is the state

| Label | Meaning |
|---|---|
| `lane:quick` · `lane:standard` · `lane:deep` · `lane:spike` | Route. The owner or the foreman sets it. |
| `status:ready` · `status:active` · `status:review` | Dispatchable · owned by a worker · PR waiting on its gate |
| `needs:owner` | Waits on a human decision. The question is in the last comment. |
| `ui` · `docs` | Picks the visual builder or the docs builder. |

Each issue body holds these fields:

- **Goal**
- **Acceptance criteria** (checkable)
- **Touches** (expected files or modules)
- **Source** (spec, ADR, or parent issue)
- **Depends on #n**

One issue produces one branch (`issue/<n>-<slug>`) and one PR, whose body says `Closes #n`. Only the foreman changes labels, merges, and closes issues.

## Shared rules (every session)

- Load the `agent-guardrails` skill before you implement, test, review, or claim completion.
- Make the smallest change that meets the acceptance criteria. Put extra ideas in one line of your report, not in code.
- **TDD** applies to every behavior change in the standard and deep lanes (the `tdd` skill):
  - for each acceptance criterion without coverage, write one failing test whose expected values come from the acceptance criteria or a hand-worked example;
  - show the red run, then the green run;
  - before you add a test, extend an existing one if it fits.
- Run only the checks your brief assigns. Do not rerun a check that is already green unless something relevant changed.
- Run slow commands (full suites, builds, `gh run watch`) in the background where your host allows it, and never sleep-poll.
- **Talking to the foreman** happens on GitHub: post the comment your role asks for, run the wake-up step if your brief specifies one, then end your turn.
- Workers are child sessions. Do not run `memo` or write shared memory, wiki, or knowledge notes; global "parent session" rules do not apply to you.
- Workers never start other factory workers, merge, push to `main`, edit labels, or close issues.

## Writing workers (builder, tester, writer)

1. **Preflight before any write.** Check that your cwd, branch, and base match the brief. If anything differs, post `BLOCKED: <mismatch>` on the issue and end your turn.
2. Do your role's part:
   - `tester`: write tests only, and commit them red with a run that shows them failing for the right reason.
   - `builder`: red → green → refactor. In the deep lane, the tester's tests are the oracle: never weaken them. If you think a test is wrong, post `BLOCKED: <why>` and end your turn.
3. For any decision the brief does not cover (scope, an interface, an ambiguous acceptance criterion), post `BLOCKED: <question>` on the issue and end your turn. Never guess an owner decision.
4. Commit in small steps with messages like `<type>: <what> (#<n>)`, then push the branch.
   - Builders and writers open the PR with `gh pr create --fill --body "Closes #<n>"`.
   - Testers push only.
5. Post a report as a PR comment, or as an issue comment if no PR exists. Include:
   - each command you ran and its red/green result;
   - each acceptance criterion marked ✅ with evidence, or ❌ with the reason;
   - any checks you skipped;
   - one line of extra ideas.
6. End your turn. A fix pass, if any, arrives as a follow-up message.

## Read-only workers (reviewer, verifier)

- **Reviewer**: apply the dispatch contract pasted in your brief. Post one PR comment that ends with the verdict `pass` or `fix-first`. Then end your turn. Never edit files or start a recheck.
- **Verifier**: build the artifact and drive the issue's user journey through the real CLI or browser. Post what you observed against each acceptance criterion. Then end your turn. Report a failure; do not fix it.

## Planning (owner sessions)

New behavior starts with `shape-design` (spec), then `write-implementation-plan` (plan), then `/to-issues`; `planning-contract` classifies artifacts. Owner decisions made during a run go into the affected spec or plan before dependent work continues. A trivial edit needs no plan.

## Repository contexts

This repository hosts two independent products in two product areas with a
joint integration area. `products/ariadne/CONTEXT.md` is the Ariadne
vocabulary; `products/lumio/CONTEXT.md` is the Lumio vocabulary (ownership
unchanged; see `CONTEXT-MAP.md`). Scoped package instructions live in
`products/lumio/packages/lumio-wiki/AGENTS.md` and
`products/lumio/packages/lumio-lancedb/AGENTS.md`;
Lumio records keep their original IDs under `products/lumio/project/`, where
`AGENTS.imported.md` is a preserved historical reference, not active
guidance. Never merge the products' test trees into one import namespace.
