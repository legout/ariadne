# Specification: Project status command

**Proposed scoped Git-only amendment (2026-10-16):** [Specification 0027, written revision 1](2026-10-16-0027-core-git-only-authoring.md) captures the owner-approved bounded Core direction; its written review is pending. Git-only status replaces legacy/staged backlog routing; source-free diagnosis and honest unadmitted/incomplete state reporting remain. Unaffected original approval remains; no implementation or shared #76 contract is approved by this notice.

| | |
| :--- | :--- |
| **Status** | **Approved, revision 2** — Owner, pi session 2026-10-12: approved by the explicit implementation authorization for issues #62–#65 (together with ADR-0021 and the scoped spec-0001 usability amendment) |
| **Origin** | Owner request 2026-10-12: usability gap table from the ktx comparison ("`ariadne status` readiness"), packages `ariadne-data`/`ariadne-agent` confirmed on PyPI |
| **Scope approved** | Revision 2: one read-only `ariadne status` reporting project kind, declared sources, route-specific governance state, staging/proposal backlog, answer-example count, packaged-skill drift and ordered next steps. Explicit diagnostic resolution works before admission or a metric catalog, without altering query-command resolution. |
| **Existing contracts** | [ADR-0021](../adr/0021-usability-shell-composition.md) (shared seams, no autonomous authority), [spec 0001](2026-09-23-0001-local-artifact-runtime.md) (legacy selectors and proposed scoped human-output amendment), [spec 0009](2026-10-02-0009-modular-core-git-authoring.md) (admission state), [spec 0010](2026-10-02-0010-context-layer-schema-and-identifiers.md) (context-only admission), [ADR-0011](../adr/0011-context-carrying-answers-and-skill.md) (packaged skill). HTTP probes are not reused: their lazy runtime construction can open sources. |
| **Contract** | planning-contract v1; installed skill provenance unknown |

## Purpose and boundary

Give humans and agents one command that answers "what is this project, and what is the next step?" without learning the route model first. Today that requires reading `ariadne.yaml`, checking for `.ariadne/`, listing `staging/`, and knowing which command reports admission. `ariadne status` reports readiness as data.

Non-goals: opening or probing any source connection; compiling or validating the catalog; repairing anything; network calls (no version check); changing `ariadne-skill status` internals; a watch or daemon mode.

## Interface

```bash
ariadne status [--project DIR | --sources PATH | --db PATH]
               [--served PATH] [--staging PATH] [--json]
```

### Diagnostic resolution, not query-runtime construction

- `--project DIR` explicitly selects managed diagnostics at that existing directory, including a scaffold with no `.ariadne/` records or admission yet. It conflicts with legacy `--sources`/`--db`/`--served` selectors, exactly as on the managed query route.
- With no explicit route selector, a cwd `.ariadne/` state directory selects managed **diagnostics only**; malformed or incomplete state reports its blocker, never a fallback to root artifacts. An ordinary `.git` directory alone is not a managed-project marker. A new managed scaffold before proposal creation is diagnosed with explicit `--project` by setup.
- Otherwise diagnose the legacy project at cwd. `--sources`/`--db` select source configuration only, not artifact roots. `--served PATH` explicitly selects an existing legacy artifact directory, even before its layers exist. Without it, reuse the query CLI's cwd-versus-`./served` artifact-root ambiguity check when promoted roots exist; two valid roots refuse and name `--served` as the remedy. Zero promoted roots is diagnostic data, not a query-runtime startup error.
- Staging defaults to `staging/` beneath cwd (legacy) or the logical project root (managed), or uses the explicit `--staging` path. An empty cwd with no scaffold/artifacts reports `kind: none`. Invalid explicit directory selectors are errors.

This is a new read-only diagnostic resolver, not an assertion of existing automatic managed detection in query commands. Share the applicable artifact/root helpers, registry parsers and operational-state readers; never construct `QueryRuntime`, compile models or initialize `DuckDBExecution`.

### Report

Sections, in fixed order:

1. **project** — `kind: none | legacy_staged | git_managed`, resolved logical/artifact roots, Git availability/repository-root/commit-identity prerequisites for managed authoring, and recorded admission `none | valid | invalid`. A valid managed admission names its pinned revision/digest after the existing artifact/evidence consistency checks; absent or invalid admission never serves mutable artifacts as its replacement.
2. **sources** — count/types from the selected registry; distinguish scaffold declarations from admitted configuration and pending proposals. Managed approval is evaluated for each **complete resolved registry identity and proposal revision**, as the existing source-approval seam records it, not independently guessed per source. Report identities/digests and state without credential values; do not connect.
3. **work_pending** — legacy staged-artifact count and `review_needed` markers; managed proposal IDs/revisions and validation state; answer-example counts by review status. Missing optional stores mean zero, not failure.
4. **skill** — existing packaged-asset hash/drift states, with scope and agent target retained. Missing optional host targets do not make an installed target drifted; installation is not inferred from unrelated user-scope copies.
5. **next_steps** — ordered exact commands for actual blockers: Git preparation, source approval, authoring/repair/validation, human review/admission or skill wiring. A `review_needed` artifact never gets an unconditional promotion recommendation. No command is executed.

The overall `ready` flag means **artifact prerequisites for governed metric querying are present**: selected served catalog metadata and source configuration are readable, and managed admission/approved identity or the existing legacy served state is usable. It does not prove compilation, live source health or numerical correctness. A context-only managed admission reports metric readiness false with context available; optional skills, examples and pending drafts do not invalidate an otherwise usable served catalog. Sections retain their explicit states and reasons rather than treating backlog counts as failures.

`--json` emits exactly one structured report; otherwise present its states as aligned human text. This new-command-only exception is the **proposed** amendment in spec 0001, requiring approval with this spec. Existing query stdout/stderr contracts are unchanged. A produced report exits 0 even when not ready; invalid selectors/ambiguous roots fail nonzero.

## Failure and consistency behavior

- Missing project/admission/catalog is report data. Corrupt or unreadable state is explicitly invalid/unavailable, not a healthy empty state; other readable sections remain visible.
- No writes, source connection, model compilation, network call or metric query. Readiness cannot be implemented via the existing eager QueryRuntime or HTTP probe.
- Commits and validation labels alone never establish admission. Candidate declarations may be listed as pending but never labeled served.

## Acceptance criteria

1. Empty cwd yields `kind: none`, `ready: false` and a setup hint, exit 0; an explicit managed scaffold with no admission also produces a report instead of the query factory's missing-admission error.
2. Legacy staging and managed pending proposals retain their own identities/states. Ready served artifacts remain ready with optional stores absent or drafts pending; failed/`review_needed` work is directed to repair/review, not blindly promoted.
3. Managed valid admission reports the checked pinned revision/digest; absent, corrupt or changed snapshot/evidence reports a blocker and never falls back. Context-only admission is distinguished from a metric catalog.
4. A focused fixture makes source connection, QueryRuntime construction, model compilation and network entry points fail if called; status still reports from metadata and changes no project files.
5. `--json` parses as one object with the same reported states as human output; existing query commands keep their established output contracts.
6. Two valid legacy roots refuse with actionable `--served` guidance; explicit selection resolves that ambiguity. `.git` alone does not imply managed admission, and status-only diagnostic detection does not alter query routing.
7. Git authoring prerequisites and per-target skill drift appear with actionable next steps; no missing optional host target is misreported as a failed installed target.

## Shaping capture checkpoint

- **Vocabulary:** no new canonical domain terms; the report reuses Project, Source Registry, Staging, Promotion, Git Review Admission, Answer Example as defined in [CONTEXT.md](../../CONTEXT.md). "Readiness" is report data, not a lifecycle state, and grants nothing.
- **Decisions:** composition-only and no-authority constraints are recorded in [ADR-0021](../adr/0021-usability-shell-composition.md). Exit-code-as-data (0 with structured readiness) over exit-code-as-gate is a local UX choice; no separate ADR warranted.
- **Behavior:** scope, non-goals and acceptance above; approved as revision 2 (see Status).
- **Uncertainty:** diagnostic selection and the bounded meaning of readiness are explicit above. Exact JSON key layout is implementation latitude; the shared artifact/state seams and preservation of existing query contracts are prerequisites, not optional optimizations. Approval is recorded in the Status row; no material decision remains open for implementation.
