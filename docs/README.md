# Ariadne documentation

This documentation targets Ariadne 0.6.1 and is organized by reader goal, following [Diátaxis](https://diataxis.fr/). Choose one type based on what you need to do:

## Tutorials

- [Lumio + Ariadne locally](tutorials/lumio-ariadne-local.md) — start here for a complete example: knowledge, reviewed release, 150 EUR result, citations and an explicit update. No Docker, S3 or model key.

- [Get started](tutorials/getting-started.md) — learn by creating a project and reaching a first governed query.

## How-to guides

- [Local Lumio Git workflow](how-to/lumio-git-local.md) — sync content, inspect admitted identity and explicitly activate a reviewed Bound Release.
- [Git-backed authoring](how-to/git-authoring.md) — create and review proposals, admit a catalog, explicitly reauthor content for a fresh Git project; no legacy-state import.
- [Multiple S3 storages](how-to/multiple-s3-storages.md) — read two independently credentialed S3-compatible storages through named, credential-free profiles (optional; requires the appropriate runtime extensions).
- [Context knowledge](how-to/context-knowledge.md) — refresh schema facts, resolve terms, inspect mappings, and author routing guidance.
- [Docker MCP](how-to/docker-mcp.md) — run the optional containerized MCP service with an external project.

## Reference

- [CLI](reference/cli.md) — commands, options, project selectors, and transport entry points.
- [Data sources](reference/data-sources.md) — supported source types and registry fields.
- [Lumio bound releases](reference/lumio-bound-releases.md) — supported local profiles, exact package pairing, scope and overall admission.
- [Context knowledge](reference/context-knowledge.md) — page types, structured metadata, limits, and role capabilities.
- [Git migration mapping](reference/git-authoring-migration.md) — exact legacy-to-Git behavior and unchanged routes.
- [Ariadne Agent API](../ariadne-agent/README.md) — Python API and conversation contract.

## Lumio foundation docs

The Lumio Knowledge Base foundation lives in the same repository as an
independent product (no Ariadne installation needed):

- [Quickstart](lumio/quickstart.md) — build, review and publish a Knowledge Base.
- [Usage](lumio/usage.md) and [KB format](lumio/kb-format.md).
- Optional [S3 publication](lumio/howto-s3-publish.md) and [packaging](lumio/packaging.md).
- Package README: [`packages/lumio-wiki`](../packages/lumio-wiki/README.md).

## Explanation

- [How Ariadne works](explanations/how-ariadne-works.md) — why the layers are separate and what the governance signals mean.

Specifications, ADRs, and domain vocabulary are project design artifacts, not user guides: see [project/specs](../project/specs/), [project/adr](../project/adr/), and [CONTEXT.md](../CONTEXT.md).
