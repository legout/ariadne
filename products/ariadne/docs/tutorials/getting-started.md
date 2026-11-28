# Getting started with Ariadne

This tutorial takes you from an empty directory to a governed query. One `ariadne` executable does everything; no server, model key or cloud is needed. Ariadne prepares the work, but source approval and calculation approval are yours: `ariadne approve` only runs on an interactive terminal.

## Prerequisites

- Python 3.14 or newer and [uv](https://docs.astral.sh/uv/)
- Git
- The data owner's agreement on source access and on the business definitions

```bash
uv tool install ariadne-data      # or: ariadne-data[documents] for PDF/DOCX
ariadne --help
```

## 1. Create the project

Make the directory its own Git repository with a local identity, then scaffold it (`init` never configures Git itself):

```bash
mkdir retail && cd retail
git init
git config user.name "Your Name"
git config user.email "you@example.org"
ariadne init .
```

`ariadne init --yes` never prompts and refuses without a Git identity. Under `.gitignore`, `data/*` is ignored except `data/seed_notes.md`: source files and documents under `data/` are not versioned.

## 2. Declare a source and approve it

Put a data file under `data/` and declare it in the one active draft:

```bash
ariadne add data/events.parquet --name events
```

Declaring is inert: nothing is opened or granted. Now the human runs the **source approval**, on a terminal:

```bash
ariadne approve
```

It shows the exact source identities, reads nothing, and asks `[yes/no]`. Only then is a source grant recorded.

## 3. Author the semantic layer and context

Write `data/seed_notes.md` with the owner: business domain, row grain, dates, units, exclusions. Then apply typed edits, one JSON file each (`{"kind": "model", "name": ..., "content": ...}`, `{"kind": "seed_notes", ...}`, `{"kind": "pages", "pages": [{"path": ..., "content": ...}]}`):

```bash
ariadne draft edit edit-model.json
ariadne draft edit edit-notes.json
ariadne draft edit edit-pages.json
ariadne draft status
```

The exact shapes (an OSI model plus table, reference, policy and metric knowledge pages) are in `products/ariadne/packages/ariadne-data/tests/setup_wheel_walkthrough.py`, which runs this whole sequence end to end. A coding agent can do these edits through the packaged skill (`ariadne skill install`) and the MCP authoring tools (`ariadne serve --toolset authoring`); it never approves.

## 4. Validate, inspect, preview

```bash
ariadne validate
ariadne diff
ariadne preview event_count        # from the draft: governed: false
```

`validate` checks the exact final revision against the granted sources. A stale draft (the served revision moved on) needs `ariadne draft rebase`; `ariadne draft discard` drops it (`--stale` only discards a stale draft).

## 5. Approve the calculation and query

The human runs the **calculation approval**:

```bash
ariadne approve
```

Then:

```bash
ariadne status
ariadne metrics
ariadne query event_count
ariadne query event_count --by label
```

The answer carries `governed: true`, the compiled SQL and the full Policy context; keep those caveats with the number. `governed: true` is not independent numeric attestation.

## Where the admitted pages live

After the calculation approval, the admitted knowledge pages are in the publication directory (default `~/.local/share/ariadne/published/<uuid>/versions/<revision>/`, set in the machine-local private settings) and in the approved Git revision. The working tree's `knowledge/` keeps only the scaffold files. Read admitted pages with `ariadne page PATH` or `ariadne search TEXT`, not by looking in the working tree.

## Onboarding a document

Place a PDF or Markdown file under `data/docs/`, open a draft (any edit), and let the agent call the `authoring_inputs(documents=["rules.md"])` MCP tool. It returns the resource, a sha256 digest and bounded text; there is no CLI command for it. PDF/DOCX need `ariadne-data[documents]`. The original is not versioned (`data/*` is ignored): cite resource and digest in a page. Graph traversal, ingest and publishing of a general knowledge base belong to the `lumio-wiki` skill and CLI.

## Next steps

- [CLI reference](../reference/cli.md)
- [How Ariadne works](../explanations/how-ariadne-works.md)
- [Git-backed authoring](../how-to/git-authoring.md)
- [Data source reference](../reference/data-sources.md)
- [Docker MCP](../how-to/docker-mcp.md)
