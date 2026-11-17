# Getting started with Ariadne 0.8.0

This tutorial takes a data owner from an empty project directory to a fresh query against a human-admitted Git catalog. Ariadne can prepare the work, but it does not make the owner's source-approval, review, or admission decisions.

This is the current local route: one native Lumio Knowledge Base and the OSI
semantic layer in your project, without a server or cloud. The
[historical joint example](../../../../integration/docs/tutorials/lumio-ariadne-local.md)
preserves the older Core 0.6.0 / SDK 0.4.0 numerical journey, not this setup contract.

## Prerequisites

- Python 3.14 or newer (spec 0026: 3.12/3.13 support ended with the MCP 2.2.0 migration)
- [uv](https://docs.astral.sh/uv/)
- The data owner's agreement on source access, business definitions, and which metrics should be governed
- Git for the default Git-managed authoring route

Install the core CLI:

```bash
uv tool install ariadne-data==0.8.0
```

No server or LLM credential is required for local CLI queries. Optional transports and packages are listed in the [CLI reference](../reference/cli.md#optional-transports-and-packages).

## Create a project

Native authoring needs Git first. Create the project directory, make it its
own repository and set a repository-local identity (setup never initializes or
configures Git itself):

```bash
mkdir retail && cd retail
git init
git config user.name "Your Name"
git config user.email "you@example.org"
```

Then run the setup wizard with the explicit selections that initialize one
native Knowledge Base: a `--namespace` you choose once as its stable identity,
and a machine-local `--private-profile` path outside the repository:

```bash
ariadne setup --project . --namespace "urn:uuid:your-retail-namespace" --private-profile "$HOME/.ariadne-profiles/retail.json" --agents --agent pi
```

Setup can also detect candidate data files by filename; detection is only a hint, not source approval or a schema/content scan. Without the selections (or while Git prerequisites are missing) setup only reports the actionable operator prerequisites and writes nothing except an explicitly selected skill installation.

Put data files under the project (for example, `data/`) and work with the owner to write `data/seed_notes.md`: describe the business domain, row grain, date conventions, units, exclusions, known caveats, and desired metrics. Do not infer business meaning from filenames or value frequency.

Resume the wizard at any time; an existing native Knowledge Base is validated,
never reinitialized (re-supplying the same selections validates them, and a
conflicting namespace or profile refuses):

```bash
ariadne setup --project . --namespace "urn:uuid:your-retail-namespace" --private-profile "$HOME/.ariadne-profiles/retail.json" --agents --agent pi
```

`--agents` installs the packaged Ariadne skill; `--agent` selects the host integration. Skill installation is separate from source approval and catalog admission.

## Approve sources and author the catalog

The wizard reports the project route, detected files, and next steps. For Git-managed projects, the operator reviews the proposed source identities and explicitly approves the exact proposal/digest before any source is opened for profiling. Credentials stay in the environment and are referenced by variable name in the registry.

A typical project then follows this sequence:

1. The human approves the resolved source list using the exact command and digest reported by Ariadne.
2. Ariadne's authoring workflow reads approved sources and supplied business notes, then drafts typed OSI and context artifacts in an isolated proposal.
3. Validate the final proposal revision and inspect the review report.
4. The human admits the exact reviewed and validated revision. Use the `ariadne-admit` command and digest from the review; do not substitute a commit or an agent's own approval flag.
5. Check readiness and query the admitted snapshot:

```bash
ariadne status --project .
ariadne list-metrics --project .
ariadne get-metric YOUR_METRIC --project .
```

The query is fresh: saved answer examples are method references, not cached answers. Keep the returned context and policy caveats with the number. `governed: true` identifies the human-admitted route; it does not independently attest the numeric value.

For the exact proposal commands and operator-only steps, see [Git-backed authoring](../how-to/git-authoring.md). Setup can stop at a human gate; rerunning it resumes the same project rather than approving or admitting on the operator's behalf.

## Scope and existing artifacts

This workflow targets a new Git-managed project. Core does not import legacy staged artifacts or pending review state, and it does not expose a Promotion route. Preserve existing project files; if content should move into a new project, decide explicitly what to reauthor through a revision-checked proposal. Setup never resets or silently adopts existing files.

## Next steps

- [How Ariadne works](../explanations/how-ariadne-works.md) — understand the query and governance model.
- [CLI reference](../reference/cli.md) — discover commands and project selectors.
- [Data source reference](../reference/data-sources.md) — configure local and remote sources.
- [Docker MCP](../how-to/docker-mcp.md) — optionally run an MCP endpoint in a container.
