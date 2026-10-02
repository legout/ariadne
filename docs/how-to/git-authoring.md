# How-to: Git-backed authoring — legacy → new mappings

This is the operator's migration map from the staging/Promotion authoring
workflow to Git-backed authoring proposals with human Git Review Admission
([spec 2026-10-02-0009](../../project/specs/2026-10-02-0009-modular-core-git-authoring.md)
§7, [ADR-0016](../../project/adr/0016-modular-core-git-authoring.md), issue
#39). The new workflow is not a second model loop and not a second gate: the
same deterministic checks run, the same stores stay separate, and the human
decisions stay human. Nothing here is automatic admission — **a Git commit of
existing files is never human review**.

## The new workflow in one pass

```bash
# 1. scaffold a Git-managed project (inputs only; artifact layers tracked,
#    .ariadne/, staging/ and inputs/secrets ignored; existing files kept)
ariadne-init --git myproject && cd myproject
git init && git config user.name "you" && git config user.email "you@example.com"
# declare sources in ariadne.yaml, put documents under data/docs/

# 2. the agent (or you) starts an isolated proposal — a system-generated ID,
#    branch ariadne/proposal/<id> and worktree under .ariadne/worktrees/<id>/
ariadne-authoring start --project .

# 3. source proposal + HUMAN operator approval (the only install/approve step)
ariadne-authoring propose-sources --proposal ID --expected-revision REV --file sources.yaml
ariadne-authoring approve-sources --project . --proposal ID --revision REV --source-digest DIGEST   # HUMAN

# 4. measured inputs (only the approved resolved identity is opened), then
#    complete artifact edits — one typed edit per artifact, revision-checked
ariadne-authoring inputs --proposal ID --document notes.md
ariadne-authoring read  --proposal ID --kind page --section policies --name my-policy
ariadne-authoring edit  --proposal ID --expected-revision REV --file edit.json

# 5. finalize + validate the EXACT final commit, then review it (read-only)
ariadne-authoring validate --proposal ID --expected-revision REV
ariadne-authoring review   --proposal ID

# 6. HUMAN Git Review Admission of the reviewed digest (never an agent action)
ariadne-admit --project . --proposal ID --revision REV --reviewed-digest DIGEST        # display
ariadne-admit --project . --proposal ID --revision REV --reviewed-digest DIGEST --confirm

# 7. query the pinned admitted snapshot (refuses without a valid admission)
ariadne list-metrics --project .
ariadne get-metric my_metric --project .
```

For an existing **legacy project** (staging-gate authoring), adopt Git without
losing pending work:

```bash
cd legacy-project
ariadne-init --git .        # keeps every existing file, including .gitignore
git init && git config user.name "you" && git config user.email "you@example.com"
ariadne-authoring import-legacy --project . --from-root .    # HUMAN, never admission
```

`import-legacy` copies the selected legacy artifacts — `ariadne.yaml`,
`data/seed_notes.md`, `semantic_layer/models/*.yml`, `semantic_layer/graph.yml`
and the OKF pages under `context_layer/{tables,references/joins,policies,
metrics,skills}/` — into a fresh **unadmitted** proposal, or into the
human-created initial artifact revision when the project has none yet.
Generated bookkeeping (`index.md`/`log.md` trees, computation pages) is never
imported; the finalize pass regenerates it. When the project has no artifact
revision yet, the legacy bytes become the BASE CONTENT: promotion-stamped page
claims (`verified` history, `status: stable`) survive byte-for-byte as content
without gaining new authority. When the project already carries an artifact
revision, the legacy artifacts arrive through the same typed edit interfaces
the agent surface uses — and trust claims the base does not carry are refused
by the shared forged-claims gate. The legacy `staging/` tree is never touched:
outstanding bundle, ingest, ad-hoc and example proposals stay exactly where
they were, byte-for-byte, each keeping its own review path. After the import,
the normal steps above (approve → validate → review → `ariadne-admit`)
establish the first admitted snapshot.

## Exact legacy → new mappings

| Legacy route | New route (Git-managed project) |
| :--- | :--- |
| Runtime constructors with explicit roots — `QueryRuntime(sources=..., semantic=..., context=..., staging=...)` (and the `AriadneRuntime` / `serve.Facade` aliases), or the CLI's `--served`/`--sources` flags | Project factory: `QueryRuntime.open_project(project)` / `ariadne --project DIR` — resolves the pinned human-admitted snapshot and its operator-approved source identity; a managed project without a valid admission is an explicit error, never a fallback to mutable files. The explicit legacy constructors keep working for legacy (non-Git) roots. |
| `ariadne-authoring submit --file submission.json` (one complete bundle: `{files: [{path, content}], documents, base_digest}`) | `ariadne-authoring start` + one `edit` per artifact (`{kind: model\|graph\|page\|seed_notes, ...}`) — independent, revision-checked complete edits; unchanged artifacts are inherited from the base revision instead of resent. |
| Repair chaining — `submit --base-digest DIGEST` (the CURRENT submission digest) | `edit --expected-revision REV` — the CURRENT candidate revision; a stale one is refused without overwriting. The three-round bounded repair policy is per-proposal and never reset by another commit. |
| `ariadne-authoring review` (staged-bundle review with the exact content digest) | `ariadne-authoring review --proposal ID` — exact base/candidate revisions, change inventory, bounded bodies, citations, the validation report and a review digest binding the reviewed identity. Reading either is never sign-off. |
| Promote a full Git bundle — `ariadne-promote --digest DIGEST` (staging → served, human) | Human admit: `ariadne-authoring validate --proposal ID --expected-revision REV`, `ariadne-authoring review --proposal ID`, then `ariadne-admit --project . --proposal ID --revision REV --reviewed-digest DIGEST --confirm`. Admission binds the exact reviewed+validated final commit, materializes an immutable snapshot under `.ariadne/snapshots/` and publishes `.ariadne/current.json`. |
| `ariadne-author` (profile + seed notes → LLM drafts → `staging/` → human promote) | Same loop, new destination: `python -m ariadne.author --git --sources ariadne.yaml --notes data/seed_notes.md --project .` — identical three-round behavior, output imported into a fresh unadmitted proposal; the legacy `--staging` route keeps working for legacy projects. |
| Legacy bundle state marker (`staging/authoring/bundle-state.json`, `status: validated`) | Not evidence: Git validation evidence lives under `.ariadne/validation/<proposal>/<commit>.json`, bound to the exact final commit. An old marker never carries over. |
| Rebase/merge after the admitted baseline advanced | `ariadne-authoring reconcile --proposal ID --expected-revision OLD --revision NEW` (HUMAN): records the clean new HEAD, invalidates the old revision's evidence; never merges automatically. |

## Routes that are unchanged (do not migrate them)

- **Legacy Promotion** (`ariadne-promote`, staging → served, exact-digest for
  harness-led bundle proposals) keeps serving legacy staged projects; a
  legacy promotion never writes a Git admission record.
- **Standalone document ingestion** (`ariadne-ingest` →
  `staging/context_layer/` → human Promotion) keeps its own store and gate
  (ADR-0009). It never becomes a Git proposal automatically; importing one of
  its pages into a Git proposal is an explicit human `edit`.
- **Ad-hoc metric proposals** (`ariadne define-metric` → `staging/`) stay
  `governed: false` drafts in their own store, promoted by hand.
- **Answer Examples** keep their separate store, explicit confirmation and
  operator review (`ariadne-example-review`); example review never rides the
  Git authoring gate.
- **Answer Example / ingestion / ad-hoc pending work** is never coalesced or
  admitted by the import: each keeps its own labels, store and human review.

## Combined versus split MCP startup

The MCP registrations are tool-surface separation over the same core — never
different checks or a second gate:

```bash
python -m ariadne.serve --project DIR                    # combined (default): Query + Authoring
python -m ariadne.serve --project DIR --toolset analyst   # Query operations only
python -m ariadne.serve --project DIR --toolset authoring # the authoring_ Git contract only
ariadne-analyst-mcp   --project DIR                       # the same adapter, toolset fixed
ariadne-authoring-mcp --project DIR
```

The legacy facade launch (`python -m ariadne.serve --sources ariadne.yaml
--semantic ... --context ... --staging ...`) keeps working for explicit
legacy artifact roots. No registration ever exposes source approval,
admission, `reconcile`, `import-legacy`, Promotion or example review: those
are human-only local commands (ADR-0013, spec §5).

## What an agent may never do

- run `ariadne-authoring approve-sources`, `ariadne-admit`,
  `ariadne-authoring reconcile`, `ariadne-authoring import-legacy`,
  `ariadne-promote` or `ariadne-example-review`;
- mutate Git itself (`git commit`, branch, checkout, merge, rebase, push) or
  the served/project files directly — every artifact change goes through the
  typed `ariadne-authoring` proposal seam;
- treat a commit, a validation report or its own reading of a review as
  sign-off.
