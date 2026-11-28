# How to author a Git-managed project

Use this guide to author, review and approve a change in a Git-managed project with the one `ariadne` CLI. For the exact command set see the [CLI reference](../reference/cli.md); for the model see [How Ariadne works](../explanations/how-ariadne-works.md). A new project starts with the [getting-started tutorial](../tutorials/getting-started.md).

A project has one active draft. The first edit opens it; a competing writer is refused as stale.

## Declare and approve sources

Declare sources in the draft (inert; nothing is opened or granted):

```bash
ariadne add data/orders.parquet --name orders
```

Optional named `storages:` S3 profiles (see [Multiple S3 storages](multiple-s3-storages.md)) are credential-free variable names and scopes. To change one declared source use a typed `source_change` edit through `ariadne draft edit FILE`.

**`ariadne approve` is human-only** and runs on an interactive terminal. On a draft that adds or changes a source it is a *source approval*: it shows the exact identities and, after your `yes`, records the grant. Keep sources in their own draft.

### Managed shared-workspace exception

An explicitly configured shared workspace may execute only the exact operation shown in its separately authenticated browser review. Source Approval and the requester's data authorization are distinct reviews; submission review and overall admission are distinct stages. This does not make `ariadne approve` agent-operated, and neither prompt assent nor an API token is publication authority. See [Shared workspace data](shared-workspace-data.md).

## Draft, validate, review

Documents go under `data/docs/` and are read by the `authoring_inputs` MCP tool (see the packaged skill, "Onboard a document"). Apply typed edits and validate:

```bash
ariadne draft edit edit.json
ariadne draft status
ariadne validate
ariadne diff
ariadne preview my_metric          # governed: false
```

If the served revision moved past the draft's base, the draft is stale: run `ariadne draft rebase` (human) or `ariadne draft discard` (confirmation or `--yes`). `--stale` is only for a draft stranded by a moved or copied project; it refuses for this project's own draft.

## Approve the calculation

```bash
ariadne approve
```

The human reads the exact validated revision and answers `yes`. A Git commit, successful validation or an agent-authored field is not a substitute. Then:

```bash
ariadne status
ariadne metrics
ariadne query my_metric
```

After approval the admitted pages live in the publication directory (default `~/.local/share/ariadne/published/<uuid>/versions/<revision>/`) and the approved Git revision; the working tree's `knowledge/` holds only the scaffold. Read them with `ariadne page PATH`.

## Scope and existing projects

This workflow is for a new Git-managed project. Core does not import legacy staged artifacts or pending review state. Preserve existing files and decide with the owner what to reauthor into a new draft. See the [Git-only route reference](../reference/git-authoring-migration.md).
