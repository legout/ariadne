# Specification: Setup onboarding wizard

| | |
| :--- | :--- |
| **Status** | **Approved, revision 2** — Owner, pi session 2026-10-12: approved by the explicit implementation authorization for issues #62–#65 (together with ADR-0021 and the scoped spec-0001 usability amendment) |
| **Origin** | Owner request 2026-10-12: usability gap table from the ktx comparison ("`ariadne setup` wizard", "`setup --agents`"); `ariadne-skill install` already exists and is composed, not rebuilt |
| **Scope approved** | Revision 2: scaffold/resume, explicit Git prerequisite handoff, filename-only source suggestions and inert typed declarations, never source approval, real per-host skill wiring, authoring guidance and optional deliberately selected legacy authoring, plus the public PyPI-first quickstart. |
| **Existing contracts** | [ADR-0021](../adr/0021-usability-shell-composition.md) (composition, TTY-gated human steps, no new authority), [spec 0009](2026-10-02-0009-modular-core-git-authoring.md) (Git proposal loop), [ADR-0016](../adr/0016-modular-core-git-authoring.md) (managed route), [ADR-0011](../adr/0011-context-carrying-answers-and-skill.md) (packaged skill), [spec 0016](2026-10-12-0016-project-status-command.md) (status), [CONTEXT.md](../../CONTEXT.md) (Source Approval is human) |
| **Contract** | planning-contract v1; installed skill provenance unknown |
| **Approved source-hint extension** | Owner approved written revision 1 with “approved.” in the Pi conversation 2026-10-13, captured in [approved specification 0022](2026-10-13-0022-native-duckdb-sources.md): add the filename-only `*.duckdb` → `duckdb` suggestion. Only this scoped filename-hint addition is approved. Detection still opens no catalog or source data, binds no views and grants no approval; existing file hints, route preservation and human handoffs are unchanged. |

## Purpose and boundary

Reduce "from nothing to first governed answer" to one entry command with guided steps, matching the adoption bar set by ktx's `ktx setup` without copying its structure. The wizard is an orchestrator over existing commands (`ariadne-init`, registry editing, `ariadne-author`, `ariadne-skill install`, `ariadne status`), not a second implementation of any of them.

Non-goals: no new runtime dependencies (plain stdin prompts), telemetry, ambient network calls or LLM-provider management; no source approval, admission, Promotion, reconciliation or Git initialization/configuration by setup; no automatic full-bundle drafting/validation loop or legacy migration; no editing of served layers. Inert proposal preparation reuses the existing typed seams; a deliberately selected existing authoring step retains its disclosed source/LLM access.

## Interface

```bash
ariadne setup [--legacy] [--project DIR] [--no-input]
              [--agents [--agent universal|pi|claude|hermes] [--scope project|user]]
```

A **new** project defaults to managed scaffolding (`ariadne-init --git`); `--legacy` explicitly selects staged scaffolding. Existing route state is preserved: managed metadata selects managed, legacy served/staged artifacts select legacy. An existing scaffold without a recorded route requires an operator choice (or `--legacy` for staged); non-interactive execution prints the choice needed rather than converting it. No rerun migrates a legacy project or rewrites existing init files.

`--no-input` or non-interactive input/output performs only scaffold creation, filename detection, explicitly configured skill installation and reporting. It never accepts detected sources, edits a registry/proposal, runs authoring or invokes a human-only operation. The shared new-command output exception is proposed in spec 0001; existing query outputs remain unchanged.

Steps, each skippable and reported:

1. **Scaffold or resume.** Delegate to `ariadne-init` with the selected route, retaining its existing collision/path checks. Inspect the diagnostic status from spec 0016 even when no catalog/admission exists. A new managed scaffold is not yet a Git repository.
2. **Git prerequisites (managed).** Check Git availability, that the project is its own repository's top-level root, and configured operator commit identity. If missing, print the operator's `git init` / repository-local `git config user.name` and `user.email` steps and pause proposal preparation. The wizard never initializes/reinitializes Git or changes global/local Git configuration. Resume after the operator completes those steps; the existing proposal seam handles creation of an initial artifact commit where applicable.
3. **Source detection and inert declaration.** Inspect filenames only in a bounded project scan, skipping hidden dirs, `.git`, virtualenvs, `node_modules`, `staging/` and `.ariadne/`. `*.db`/`*.sqlite`/`*.csv`/`*.json`/`*.parquet` extensions are editable type hints, not content/schema validation or access approval; no source bytes are opened or parsed. Postgres uses an environment-variable name for the DSN, never an inline credential or printed environment value. Interactive operators select/edit the proposed entries before any declaration write. On managed projects, choose an existing proposal or use the existing `start` seam, then declare entries through revision-checked `propose-sources`; return the actual proposal ID, revision and complete resolved source digest. Do not directly edit a managed project's root registry. On legacy projects, write only the explicitly accepted declarations through the existing registry/proposal seam. Identical entries are not duplicated; conflicting identities are reported, not renamed or silently overwritten.
4. **Source approval handoff.** Declaration is not approval. For the managed proposal, print `ariadne-authoring approve-sources --project DIR --proposal ID --revision REV --source-digest DIGEST` with the returned identities; legacy source-proposal approval uses its retained human command. Setup **never invokes source approval**, even at a TTY, and pauses source/authoring work while approval is pending. It may still finish skill installation and the diagnostic report.
5. **Authoring handoff or explicit delegated run.** For a newly approved-ready legacy project, an interactive operator may deliberately select the existing `ariadne-author` call after seed-note guidance and disclosure of profiling access and configured LLM egress. That call retains its own existing source-access rules and stages drafts only; setup never promotes. Without the required configuration/approval, or in non-interactive mode, print the next steps instead. Managed projects receive the harness-led instructions (agent's own model, no second credential); automatic drafting/validation of a full Git bundle is not added here. Authoring through approved sources and the configured LLM may use its existing network access; detection/status/skill install never do.
6. **Skill target and scope.** `--agents` prompts for universal, Pi, Claude or Hermes when `--agent` is omitted interactively; non-interactive runs require an explicit target or print the missing selection and install nothing. Scope defaults to project; user scope requires the explicit choice. Delegate to `ariadne-skill install --scope SCOPE --agent TARGET` for Pi/Claude/Hermes, or omit `--agent` only for universal. Project-scoped delegation runs at the selected project directory, not the caller's unrelated cwd. Report each selected canonical copy and host link with the existing hash/status machinery; universal installation is never claimed to activate Pi/Claude/Hermes. Unselected targets do not need to exist. No installer/manifest is duplicated.
7. **Finish.** Print diagnostic status and actual next steps, preserving source/admission blockers. A successful scaffold/skill install is not reported as a query-ready catalog.

## Skill and public-documentation contract

The packaged skill says setup is operator-facing; agents may use `setup --no-input` for scaffold/detection output and explicitly selected skill installation, never satisfy prompts or run the human-only approval/admission/Promotion/reconciliation commands. `ariadne review` remains operator-only per spec 0019. Describe universal versus host-specific skill wiring honestly.

Update README's public quickstart from editable-install-first to `uv tool install ariadne-data`, then setup, the chosen authoring route, human review/admission and the first fresh governed query. Preserve a separate source-development install path. Explain that `ariadne-agent` is an optional conversational host, not needed for the core CLI; MCP remains optional. The walkthrough must explicitly include Git prerequisites, source approval, seed-note/domain clarification, target-specific skill installation and governed-versus-attested wording. Do not present unreleased commands as available in the currently published 0.2.0 package; the implementation handoff verifies against its installed candidate wheel before separately authorized release/publication.

## Failure and consistency behavior

- No candidates means zero detected files and manual declaration guidance. Unreadable directory metadata is reported per path; filename detection makes no content-parse claims.
- Missing Git or identity blocks proposal preparation with actionable operator instructions, not all local setup/reporting. An existing unadmitted proposal is resumed, never replaced to bypass errors or create duplicate source entries.
- Interrupted operations retain their existing seam's recovery/refusal rules. Report completed steps and remaining blockers; never promise byte-identical rollback of an already completed scaffold, proposal edit or authoring run.
- Without `--agents` no skill files are touched; unknown host choices refuse rather than inventing a target.

## Acceptance criteria

1. A new managed scaffold reports absent admission and missing Git prerequisites rather than claiming readiness; after operator Git preparation, selected sources are proposed through the existing typed seam and setup prints the exact human approval command without calling it. Explicit `--legacy` retains staged onboarding.
2. Resume preserves route/existing files and reuses the selected proposal; identical declarations create no duplicate entry or replacement proposal. Ambiguous scaffold-only route selection requires a choice, not implicit migration.
3. For `--agents --agent pi|claude|hermes`, the selected canonical skill and correct host-specific project link/copy match packaged assets. Universal is labeled universal-only. Running from outside `--project DIR` still installs inside DIR; no unrelated target is overwritten by the shell.
4. Detection opens no source content and performs no query. Declaration confirmation is separate from source approval; no credential value is stored or emitted. Non-interactive execution accepts no source list and writes no registry/proposal.
5. Setup never calls source approval, admission, Promotion or reconciliation in any mode. Non-TTY/`--no-input` runs no authoring and prints the remaining human steps.
6. Status/detection/skill installation make no network calls and add no dependency. Only an explicitly selected existing authoring step may profile authorized sources or call its configured LLM, with that access disclosed beforehand.
7. The packaged skill documents operator steps and real host wiring; drift checks are scoped to chosen targets, not every optional host directory.
8. README's release-facing quickstart uses `ariadne-data` from PyPI, shows optional `ariadne-agent`, Git/approval/review/first-query and agent-target steps. Source-checkout instructions remain available separately; the installed candidate-wheel walkthrough proves the described new commands, without implying release authority.

## Shaping capture checkpoint

- **Vocabulary:** no new canonical domain terms; Setup is CLI chrome. The scan reuses Source Registry, Source Approval, Staging, Promotion, Git Review Admission as defined.
- **Decisions:** shared composition, strict source-approval handoff, operator-only review delegation and no ambient costs are recorded in [ADR-0021](../adr/0021-usability-shell-composition.md). Managed-by-default applies only to new scaffolds; existing projects are not migrated. The new-command output exception is a proposed scoped amendment in spec 0001.
- **Behavior:** scope, non-goals and acceptance above; approved as revision 2 (see Status).
- **Uncertainty:** v1 automatically suggests only the listed file extensions; DuckLake and other registry types remain explicit operator declarations, not detector heuristics. Git prerequisites, source handoff, real host targets and public-doc coverage are specified above; approval is recorded in the Status row.
