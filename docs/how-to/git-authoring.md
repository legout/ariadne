# How to author a Git-managed project

Use this guide to prepare, review, and admit a Git-backed proposal. It is a task guide: for exact command/surface mappings see the [Git migration reference](../reference/git-authoring-migration.md), and for the governance model see [How Ariadne works](../explanations/how-ariadne-works.md).

For a new project, the [getting-started tutorial](../tutorials/getting-started.md) covers scaffolding and first setup. This guide starts from an initialized data-project repository with a local Git identity.

## Create and admit a proposal

Declare the source registry in `ariadne.yaml` and put any operator-approved documents under an allowed project path. Start a proposal:

```bash
ariadne-authoring start --project .
```

The command returns a proposal ID and candidate revision. Use those current values in the following commands; do not guess or reuse stale revisions.

### Propose and approve sources

Submit source declarations as inert entries, then have the human operator inspect and approve the resolved source identity:

```bash
ariadne-authoring propose-sources --project . --proposal ID \
    --expected-revision REV --file sources.yaml
ariadne-authoring approve-sources --project . --proposal ID \
    --revision REV --source-digest DIGEST
```

**The second command is human-only.** Use the exact ID, revision, digest, and approval command reported for the proposal. Source approval happens before a declared source is opened for authoring inputs.

### Draft and validate artifacts

The agent or operator reads approved inputs, makes typed artifact edits, validates the current revision, and reviews the result:

```bash
ariadne-authoring inputs --project . --proposal ID
ariadne-authoring edit --project . --proposal ID \
    --expected-revision REV --file edit.json
ariadne-authoring validate --project . --proposal ID \
    --expected-revision REV
ariadne-authoring review --project . --proposal ID
```

After each edit or validation, use the returned current revision. If the review identifies a problem, make a revision-checked edit and validate/review that final revision again. Reading a review report is not sign-off.

### Admit the reviewed revision

The operator inspects the final review, then admits the exact reviewed digest:

```bash
ariadne-admit --project . --proposal ID --revision REV \
    --reviewed-digest DIGEST
ariadne-admit --project . --proposal ID --revision REV \
    --reviewed-digest DIGEST --confirm
```

The first invocation previews the decision; the second performs it. Admission is human-only and binds the reviewed, validated revision. A Git commit, successful validation, or agent-authored approval field is not a substitute.

Check the managed project and query the pinned admitted snapshot:

```bash
ariadne status --project .
ariadne list-metrics --project .
ariadne get-metric my_metric --project .
```

## Move a legacy project to Git-managed authoring

A legacy project uses staging and the separate human Promotion gate. To begin an explicit migration without discarding project files:

```bash
cd legacy-project
ariadne-init --git .
git init
git config user.name "Your Name"
git config user.email "you@example.org"
ariadne-authoring import-legacy --project . --from-root .
```

Configure identity locally in this repository, not globally. `import-legacy` creates an unadmitted proposal from the selected artifact files. It does not import generated indexes/logs, does not admit anything, and leaves the existing `staging/` tree and its separate pending proposal stores untouched. Continue with source approval, validation, review, and human admission as above.

Imported legacy table pages do not have canonical resource bindings. A human must explicitly enrich a table page against exactly one approved asset before schema refresh; follow [Enrich an imported legacy table page](context-knowledge.md#enrich-an-imported-legacy-table-page).

Existing projects are never silently migrated by setup. Do not combine a legacy artifact root and a Git-managed admitted snapshot in one query route. See the [migration reference](../reference/git-authoring-migration.md) for exact old-to-new command and behavior mappings, and the [CLI reference](../reference/cli.md) for MCP startup options and human-only commands.
