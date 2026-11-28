# Getting started with Ariadne

This tutorial takes you from an empty directory to a governed query. One `ariadne` executable does everything; no server, model key or cloud is needed. Ariadne prepares the work, but source approval and calculation approval are yours: `ariadne approve` only runs on an interactive terminal.

## Prerequisites

- Python 3.14 or newer and [uv](https://docs.astral.sh/uv/)
- Git
- The data owner's agreement on source access and on the business definitions

```bash
# Install a pinned Git revision (use a commit SHA or `main`); it brings the matching lumio-wiki.
# For PDF/DOCX documents use "ariadne-data[documents] @ git+..." instead.
uv tool install --python 3.14 \
  "ariadne-data @ git+https://github.com/legout/ariadne@main#subdirectory=products/ariadne/packages/ariadne-data"
ariadne init --help
```

The PyPI `ariadne-data` 0.8.0 release predates this command set (it has no `ariadne init`), so do not use `uv tool install ariadne-data` until a newer release is published. `ariadne init --help` succeeding is the check that you have the right version.

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
mkdir -p data
uv run --no-project --with duckdb python -c "
import duckdb
duckdb.sql(\"COPY (SELECT * FROM (VALUES (1,'a'),(2,'b'),(3,'c')) t(id,label)) TO 'data/events.parquet' (FORMAT PARQUET)\")"
ariadne add data/events.parquet --name events
```

Declaring is inert: nothing is opened or granted. Now the human runs the **source approval**, on a terminal:

```bash
ariadne approve
```

It shows the exact source identities, reads nothing, and asks `[yes/no]`. Only then is a source grant recorded.

## 3. Author the semantic layer and context

Write the owner's domain notes, then apply typed edits, one JSON file each (`{"kind": "model", ...}`, `{"kind": "seed_notes", ...}`, `{"kind": "pages", "pages": [{"path": ..., "content": ...}]}`). This script writes the three files for the three-row `events` source: an OSI model (dataset `events`, primary key `id`, dimension `label`, metric `event_count` = `COUNT(*)`), the seed notes, and the smallest page set the validator accepts (table, reference, policy and metric):

```bash
python3 - <<'PY'
import json

TABLE = "ariadne://table/WyJldmVudHMiLG51bGwsImV2ZW50cyIsImV2ZW50cyJd"  # source `events`, table events
MODEL = """version: 0.3.0.dev0
name: events
description: Three events
datasets:
- name: events
  source: events.events
  primary_key: [id]
  fields:
  - {name: id, expression: {sql: id}}
  - {name: label, expression: {sql: label}, dimension: {}}
  metrics:
  - name: event_count
    expression: {sql: COUNT(*)}
    description: Count all events
"""
NOTES = "# Events\n\nOne row per unique event id; count every event once.\n"

def page(kind, title, resource, body, profile="", native=""):
    # a table page anchors the source table; the others cite a document path
    cite = "" if kind == "table" else f"        resource: {resource}\n"
    core = f"  core_ref:\n    kind: resource\n    id: {resource}\n" if kind == "table" else ""
    slug = title.replace("_", "-").replace(" ", "-").lower()
    return (f'---\nid: "entity:{slug}"\ntitle: "{title}"\nentity_types:\n  - {kind}\n'
            f'tags:\n  - {kind}\nsummary: "{body}"\nlifecycle: "approved"\nvisibility: "public"\n'
            f"sources:\n  - id: rule\n    title: Owner rule\n"
            f"ariadne_profile:\n  version: 1\n  kind: {kind}\n{profile}{core}"
            f"  native:\n    type: {kind}\n    title: {title}\n    description: {body}\n"
            f"    tags:\n      - {kind}\n    status: draft\n"
            f"    sources:\n      - id: rule\n        title: Owner rule\n{cite}{native}---\n\n# {title}\n\n{body}\n")

NO_POLICIES = "  required_policies: []\n"
PAGES = {
    "knowledge/tables/events.md": page("table", "events", TABLE, "One row per event."),
    "knowledge/references/event-rule.md": page("reference", "Event rule", "data/seed_notes.md", "All events count."),
    "knowledge/policies/all-events-count.md": page("policy", "All events count", "data/seed_notes.md",
                                                   "Count every event once.", NO_POLICIES),
    "knowledge/metrics/event-count.md": page(
        "metric", "event_count", "references/event-rule.md", "Count all events.",
        "  metric_ref:\n    model: events\n    metric: events.event_count\n" + NO_POLICIES,
        "    governed_by: references/event-rule.md\n    dimensions:\n      - label\n"
        "    grain:\n      primary_key:\n        - id\n      cardinality_enforcement: strict_1_to_1\n"),
}
open("data/seed_notes.md", "w").write(NOTES)
for name, edit in {
    "edit-model.json": {"kind": "model", "name": "events", "content": MODEL},
    "edit-notes.json": {"kind": "seed_notes", "content": NOTES},
    "edit-pages.json": {"kind": "pages", "pages": [{"path": p, "content": c} for p, c in PAGES.items()]},
}.items():
    json.dump(edit, open(name, "w"))
PY
ariadne draft edit edit-model.json
ariadne draft edit edit-notes.json
ariadne draft edit edit-pages.json
ariadne draft status
```

A coding agent can make these edits through the packaged skill (`ariadne skill install`) and the MCP authoring tools (`ariadne serve --toolset authoring`); it never approves.

## 4. Validate, inspect, preview

```bash
ariadne validate
ariadne diff
ariadne preview event_count        # from the draft: governed: false
```

`validate` checks the exact final revision against the granted sources. A stale draft (the served revision moved on) needs `ariadne draft rebase`; plain `ariadne draft discard` drops it (after a confirmation, or with `--yes`). `ariadne draft discard --stale` is something else: it retires a draft stranded by a moved or copied project (its record names another project path), without confirmation, and refuses when the draft belongs to this project.

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
