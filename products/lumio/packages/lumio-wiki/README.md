# lumio-wiki

> Portable, model-free Knowledge Base foundation for
> [Lumio](../../CONTEXT.md) — a compiled Markdown knowledge base your coding agents
> can load, validate, search, traverse, ingest, and publish, with citations
> and Git-native authoring with explicit Publication Admission. The deployable Lumio web application (chat UI,
> auth, roles, providers) lives in a separate private repository and consumes
> these published wheels. Ariadne Core (`ariadne-data`) is developed alongside
> this foundation in the same repository as another independent product;
> neither package requires the other.

**Status:** pre-1.0 MVP software, licensed Apache-2.0.

For the *why* and the vision, read the domain docs — this README documents
**what runs today**:

> **Two trust models, one Knowledge Base.** The **`lumio-wiki` CLI** (and the
> library behind it) has no accounts or roles: a coding agent with filesystem
> access authors Compiled Pages in a selected Git worktree and validates the
> complete candidate. Publication is separate: preview an exact commit, then
> confirm only after the operator authorizes the displayed review, destination
> and expected current version. A commit, passing validation or general coding
> request is not permission to publish. Hosted clients enforce their own roles.

- [`CONTEXT.md`](../../CONTEXT.md) — ubiquitous language (glossary).
- [`project/specs/0002-core-sdk.md`](../../project/specs/0002-core-sdk.md) — Core SDK PRD.
- [`project/adr/`](../../project/adr/) — architectural decisions (ADR-0025 records the
  repository split).
- [`docs/kb-format.md`](../../docs/kb-format.md) — canonical Compiled Page frontmatter reference.
- [`docs/ariadne-context.md`](../../docs/ariadne-context.md) — optional pinned Ariadne Context Profile
  consumption (exact identity, scoped pinned navigation, boundaries).
- [`docs/quickstart.md`](../../docs/quickstart.md) — canonical local/Git-first
  onboarding journey (empty project → reviewed publication → grounded search);
  the optional S3/Docker publication path lives in
  [`docs/howto-s3-publish.md`](../../docs/howto-s3-publish.md). Runnable via
  [`examples/onboarding-journey/`](../../examples/onboarding-journey/).
- Joint local tutorial (Lumio + Ariadne), canonical and cross-repository:
  [`docs/tutorials/lumio-ariadne-local.md`](../../../../integration/docs/tutorials/lumio-ariadne-local.md)
  in this repository's Ariadne-side docs. The SDK links to it; the joint
  walkthrough lives only there.

## Install

`lumio-wiki` ships as two progressively enhanced wheels (ADR-0010):

| Distribution | Installs | Use when |
|---|---|---|
| `lumio-wiki` | `msgspec[yaml]`, `msgpack`, plus the `lumio-wiki` CLI and packaged Agent Skill | You want a portable, model-free Knowledge Base from any coding agent (Pi, Hermes, Codex, Claude Code, …). |
| `lumio-lancedb` | `lumio-wiki` + LanceDB + PyArrow | You want BM25 / semantic / hybrid retrieval over the same Knowledge Base. |

```bash
pip install lumio-wiki                       # foundation: load, validate, search, traverse, ingest, publish
pip install 'lumio-wiki[documents]'          # + LiteParse/MarkItDown/AnyDoc for PDF/image/office/HTML ingestion
pip install 'lumio-wiki[llm]'                # + an unattended OpenAI-compatible Distiller
pip install 'lumio-wiki[all]'                # documents + llm together (still no LanceDB)
pip install 'lumio-wiki[s3]'                 # + S3-native KB Locations (immutable Published Versions over object storage)
pip install 'lumio-wiki[mcp]'                # + read-only MCP stdio server (official SDK; `lumio-wiki mcp <kb>`)
pip install lumio-lancedb                    # + enhanced BM25/semantic/hybrid retrieval
```

The base wheel depends only on `msgspec[yaml]` and `msgpack`; it does not
install LanceDB/PyArrow or any model provider. Quick start for MCP-capable
hosts: `pip install 'lumio-wiki[mcp]'`, then configure the stdio command
`lumio-wiki mcp <kb-path-or-s3-uri>` (see `docs/usage.md`). Optional
capabilities:

| Extra | Brings | Capability |
|---|---|---|
| `lumio-wiki[documents]` | LiteParse, MarkItDown, AnyDoc | PDF / scanned-PDF / image (OCR + page numbers), office formats, HTML. The base wheel handles text and Markdown. |
| `lumio-wiki[llm]` | `openai` | Unattended Distiller backed by an OpenAI-compatible provider. The base wheel uses the host coding agent as the Distiller. |
| `lumio-wiki[all]` | both | Document conversion + unattended distillation together. |
| `lumio-wiki[mcp]` | `mcp` (official SDK) | Read-only MCP stdio server over one bound Knowledge Base Location. |
| `lumio-lancedb` | LanceDB, PyArrow | BM25 / vector / semantic / hybrid retrieval. The canonical SDK never imports it. |
| `lumio-lancedb[embeddings]` | `sentence-transformers` | Local embeddings for the LanceDB adapter. Torch stays out of the base adapter and out of `lumio-wiki`. |
| `lumio-lancedb[s3]` | `obstore` | Remote (S3) index support. |

**Adapter selection.** `lumio-wiki` provides the always-available zero-index
retrieval; installing `lumio-lancedb` adds BM25 / semantic / hybrid retrieval
behind the same `RetrievalResult` contract. The canonical SDK stays
adapter-neutral; explicitly selected CLI/evaluation composition lazily loads the
separately installed adapter, preserving the one-way dependency graph.

## CLI reference

`uv run lumio-wiki <command>` (or just `lumio-wiki` once installed). Works
from any coding agent with no model provider and no LanceDB.

```bash
lumio-wiki --version
lumio-wiki setup <path> [--publish-to <s3-uri>] [--retrieval zero-index|lancedb] [--source-store <s3-uri|path>]  # project bootstrap: KB + .env + AGENTS.md (+ optional skill)
lumio-wiki init <path>                           # lower-level KB-only: scaffold a categorized Knowledge Base
lumio-wiki validate <kb-path>                    # exit 0 if valid, 1 otherwise
lumio-wiki status [<kb-path>]                    # effective config + retrieval state, one secret-free summary
lumio-wiki search <kb-path> "<query>"            # lexical search over titles, aliases, tags, summaries, bodies
lumio-wiki page [<kb-path>] "<title>" [--raw|--json] # lossless or bounded Compiled Page read
lumio-wiki related <kb-path> "<title>"           # list pages related to a title
lumio-wiki paths <kb-path> "<src>" "<dst>"       # shortest typed path between two titles
lumio-wiki entity <kb-path> "<name>"             # resolve a stable Entity from an exact ID, title, or alias
lumio-wiki hot <kb-path>                         # Maintainer-pinned Hot Index (retrieval ladder step 0)
lumio-wiki index <kb-path> [dir]                 # generated Navigation Index (step 1)
lumio-wiki ingest <kb-path> <source> [--distiller passthrough|llm]   # edit the selected Git worktree
lumio-wiki ingest <kb-path> <source> --compiled-page <page.md> --source-id <id>  # managed ingest: bind original source + authored page
lumio-wiki ingest-url <kb-path> <url> --compiled-page <page.md> --source-id <id>  # safe URL ingestion (HTTPS-only, bounded, SSRF-safe)
lumio-wiki ingest-research <kb-path> <report.md> --manifest <manifest.yaml> --source-id <id>  # research bundle (consulted URLs = provenance)
lumio-wiki capture session <kb> --compiled-page <page.md> --manifest <capture.yaml> --source-id <id> [--yes]  # explicit, preview-first session capture
lumio-wiki remove-page <kb> "<title>" [--reason <text>]        # stage an explicit Page Removal as worktree edits
lumio-wiki merge-entity <kb> <retired-id> <survivor-id>        # reviewed Entity Merge: retarget Claims/links, record redirect
lumio-wiki rename-page <kb> "<title>" --to "<new-title>"       # rename/recategorize/re-alias one page in the worktree
lumio-wiki publish <kb-path> --revision <full-commit-id> --to <destination> --expected-current <version-or-none>  # preview only
# Only after explicit operator authorization of that displayed review:
lumio-wiki publish <kb-path> --revision <full-commit-id> --to <destination> --expected-current <version-or-none> --confirm <review-digest>
lumio-wiki rollback <dest> --version <version> --expected-current <version-or-none>  # activate a complete local Published Version (preview/confirm)
lumio-wiki legacy-proposals inventory <kb-path>    # read-only migration inventory
lumio-wiki legacy-proposals export <kb-path> <id> --baseline <full-commit-id> --branch <name>  # preview unadmitted export
lumio-wiki source inspect <kb> --source-id <id> [--published-version <v>]  # secret-free metadata for the exact bound Source Version
lumio-wiki source fetch <kb> --source-id <id> [--published-version <v>] --output <path>  # byte-exact original, digest re-verified
lumio-wiki source link <kb> --source-id <id> [--published-version <v>] [--expires 5m]   # short-lived signed GET URL (max 1h; bearer secret)
lumio-wiki lint <kb-path>                        # read-only cross-page QA: validation, graph health, structural diagnostics
lumio-wiki cross-link <kb-path> [--stage]        # missing-link candidates ranked by Discovery Graph impact
lumio-wiki dream <kb-path> [--stage] [--semantic]  # Dream Cycle reflection; --stage applies top repairs as worktree edits
lumio-wiki export-graph <kb> [--scope public|all] [--out-dir <dir>]  # Discovery Graph to graph.json + graph.graphml
lumio-wiki import-graph <kb> <graph.json>        # apply stub pages from graph.json as ordinary worktree edits
lumio-wiki health <kb-path>                      # Knowledge Base health and diagnostics
lumio-wiki eval <kb-path> [--gold-set <f>] [--semantic [--model <name>]] [--json]  # recall@k per retrieval stage
lumio-wiki eval-ontology <kb-path> [--gold-set <f>] [--json]  # entity resolution / traversal / scope separation
lumio-wiki mcp <kb-path-or-s3-uri>               # read-only MCP stdio server over ONE KB (requires [mcp])
lumio-wiki doctor                                # install shape: version, optionals, packaged skill location
lumio-wiki skill path                              # locate packaged SKILL.md
lumio-wiki skill protocol                          # locate packaged PROTOCOL.md
lumio-wiki skill install --scope user              # explicit skill installation
lumio-wiki skill status --scope user               # inspect installed skill drift
lumio-wiki skill update --scope user               # explicitly refresh the skill
lumio-wiki publish-s3 <kb> [dest] --revision <full-commit-id> --expected-current <version-or-none> [--retrieval lancedb]  # immutable S3 version (same admission gate)
lumio-wiki rollback-s3 <dest> --version <v> --expected-current <active>  # reactivate a historical S3 version (preview/confirm)
lumio-wiki cleanup-s3 <dest>                      # report incomplete S3 version prefixes; deletes nothing
lumio-wiki diff-s3 <dest> --from <v1> --to <v2>   # deterministic delta between two immutable S3 versions
```

Git is required for authoring and admission, not ordinary reads, queries or
validation. Before ingest, select a registered branch/worktree and adopt
`.lumio-authoring.yaml` version 1 with a stable namespace and exact source
bindings. Keep originals, private Source Registry/history and artifacts outside
Git/public KB content; select `--source-registry <private-dir>` explicitly for
managed ingest/publication. Setup does not initialize Git or infer adoption.
Legacy export needs explicit `--confirm` using the preview's captured baseline;
it preserves the original store and creates an unadmitted branch, never a
publication. See the [quickstart](../../docs/quickstart.md).

`ingest --distiller llm` requires `lumio-wiki[llm]`; PDF/DOCX/image sources
require `lumio-wiki[documents]`. Both fail with actionable guidance if the
extra is missing.

## Knowledge Base format

A Knowledge Base is a directory of compiled Markdown pages (YAML frontmatter +
body). A fresh v2 setup starts with an empty ontology, so declare the types you
intend to use in `lumio.yaml` before adding Entity pages:

```bash
lumio-wiki init ./knowledge-base
mkdir -p ./knowledge-base/concepts
python - <<'PY'
from pathlib import Path
p = Path("./knowledge-base/lumio.yaml")
s = p.read_text()
s = s.replace(
    "ontology:\n  entity_types:\n  predicates:\n  redirects:\n",
    "ontology:\n  entity_types:\n    software-system:\n      description: A deployed software product or platform.\n  predicates:\n    described-as:\n      literal_kind: string\n  redirects: {}\n",
)
p.write_text(s)
PY
```

Then author a valid Entity page:

```markdown
---
title: "Technology Stack"
id: "entity:technology-stack"
entity_types: ["software-system"]
aliases: []
tags: ["technology"]
summary: "The project's technology stack."
category: "concepts"
type: "definition"
durability_rationale: "A stable reference for the project stack."
lifecycle: "draft"
visibility: "internal"
sources:
  - id: "stack-doc"
    title: "Stack decision"
claims: []
synthetic: false
---

# Technology Stack

Python-first: msgspec, LanceDB (optional adapter).
```

```bash
lumio-wiki validate ./knowledge-base
```

For the full field table, see **[`docs/kb-format.md`](../../docs/kb-format.md)**. A
categorized Knowledge Base additionally carries a versioned root Control File
(`lumio.yaml`) and marked reserved artifacts (Navigation Index `index.md`, Hot
Index `hot.md`, Activity Log `log.md`); see
[ADR-0008](../../project/adr/0008-knowledge-base-control-file-and-published-artifacts.md).

## Development

Requirements: **Python ≥ 3.14** and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                       # install the workspace members (from the repository root)
uv lock --check                               # verify the lockfile is current
cd products/lumio                             # Lumio's native development profile
uv run pytest -q -n 4                         # Lumio native full suite (four workers; never -n auto)
uv run pytest -q packages/lumio-wiki/tests    # focused tests stay serial
uv run ruff check .                           # lint (Lumio product rules)
uv run lumio-wiki validate tests/fixtures/valid   # sanity check the sample KB
```

The repository-root default is shared coordination coverage only — the
Lumio-native commands above are this package's full qualification.

### Codebase layout

```text
packages/lumio-wiki/src/lumio_wiki/       # Canonical portable Knowledge Base owner
packages/lumio-lancedb/src/lumio_lancedb/ # Optional LanceDB enhanced-retrieval adapter
```

## Packaging, ownership, and migration

Quick reference (full contract in [`docs/packaging.md`](../../docs/packaging.md)):

- **`lumio-wiki`** owns the canonical Knowledge Base model, loading,
  validation, Navigation/Hot Indexes, deterministic zero-index retrieval, typed
  traversal, Evidence/citations, Git authoring and exact-revision admission,
  the `lumio-wiki` CLI, and the packaged Agent Skill. No downward dependency.
- **`lumio-lancedb`** depends only on `lumio-wiki`. It owns LanceDB index
  lifecycle and BM25/semantic/hybrid ranking, returning the same
  `RetrievalResult` contract.

The wheels release as one lockstep family from tagged commits. The web
application lives in a separate private repository (ADR-0025).

## What works today

- **Core SDK** — load, validate (entity-claim ontology against the Control
  File), lexical/frontmatter/graph index, retrieve with citations + retrieval
  trace, source-fingerprint freshness, Markdown export.
- **Entity-claim ontology** — one stable Entity per Compiled Page;
  evidence-bearing Claims; reviewed Git Entity Merge with redirects;
  deterministic entity resolution; model-free evaluation (`lumio-wiki eval`,
  `lumio-wiki eval-ontology`).
- **Ingest & publish** — managed ingest with private Source Registry and
  Artifact Store (S3-compatible), exact source bindings, Page Removal with claim and
  body-link repair, Published Versions with binding manifests, OKF
  interchange.
- **Maintenance** — lint, cross-link candidates, Dream Cycle diagnostics
  (link, duplicate, synthesis, transitive impact), S3 published-version diff.
- **Optional Ariadne Context Profile** — versioned native Metric/Policy
  annotations preserved through authoring and publication, read back through
  immutable pinned published-context readers and scoped navigation (local,
  or pinned S3 with its explicit producer-side metadata store, from the
  0.5.0 release family; the published 0.4.1 pair carried local navigation
  only)
  ([docs/ariadne-context.md](../../docs/ariadne-context.md)). Purely optional: the
  base SDK has no Ariadne dependency and adds no CLI command or service for
  it.

## License

Apache-2.0 — see [LICENSE](LICENSE).
