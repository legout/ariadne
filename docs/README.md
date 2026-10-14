# Ariadne documentation

This documentation targets Ariadne 0.3.0 and is organized by reader goal, following [Diátaxis](https://diataxis.fr/). Choose one type based on what you need to do:

## Tutorial

- [Get started](tutorials/getting-started.md) — learn by creating a project and reaching a first governed query.

## How-to guides

- [Git-backed authoring](how-to/git-authoring.md) — create and review proposals, admit a catalog, or move a legacy project to the Git route.
- [Multiple S3 storages](how-to/multiple-s3-storages.md) — read two independently credentialed S3-compatible storages through named, credential-free profiles (development candidate).
- [Context knowledge](how-to/context-knowledge.md) — refresh schema facts, resolve terms, inspect mappings, and author routing guidance.
- [Docker MCP](how-to/docker-mcp.md) — run the optional containerized MCP service with an external project.

## Reference

- [CLI](reference/cli.md) — commands, options, project selectors, and transport entry points.
- [Data sources](reference/data-sources.md) — supported source types and registry fields.
- [Context knowledge](reference/context-knowledge.md) — page types, structured metadata, limits, and role capabilities.
- [Git migration mapping](reference/git-authoring-migration.md) — exact legacy-to-Git behavior and unchanged routes.
- [Ariadne Agent API](../ariadne-agent/README.md) — Python API and conversation contract.

## Explanation

- [How Ariadne works](explanations/how-ariadne-works.md) — why the layers are separate and what the governance signals mean.

Specifications, ADRs, and domain vocabulary are project design artifacts, not user guides: see [project/specs](../project/specs/), [project/adr](../project/adr/), and [CONTEXT.md](../CONTEXT.md).
