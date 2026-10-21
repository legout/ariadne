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

The proposed file is registry-shaped: optional named `storages:` S3 profile declarations (available in Core 0.6.0) travel alongside the `sources:` entries, reference already-declared profiles by name, and stay credential-free — only variable *names* and scopes are proposed, nothing is opened and no environment value is read during proposal creation. See [Multiple S3 storages](multiple-s3-storages.md).

**The second command is human-only.** Use the exact ID, revision, digest, and approval command reported for the proposal. Source approval happens before a declared source is opened for authoring inputs. For named profiles the approval additionally records the resolved effective endpoint binding (endpoint/region, never credentials): a changed endpoint needs its own approval and fresh evidence, while key rotation does not.

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

## Scope and existing projects

This workflow is for authoring a new Git-managed project. Core does not import legacy staged artifacts, pending review state, or original documents; it provides no Promotion or legacy-table enrichment path. If you have an existing project, preserve its files and decide explicitly with its owner what to reauthor into a new proposal. Setup never resets or silently adopts them.

Do not query a plain artifact root: governed query and discovery require a valid human-admitted Git snapshot. See the [Git-only route reference](../reference/git-authoring-migration.md) for the supported boundaries and the [CLI reference](../reference/cli.md) for commands and MCP startup options.
