# Lumio Usage Guide

How to use Lumio three ways: from the **CLI**, as a **Python library**, and
inside a **coding-agent harness** (opencode, Claude Code, Codex, etc.).

> New here? **[`docs/quickstart.md`](quickstart.md)** is the canonical
> onboarding journey (issue #180): one linear local path — Maintainer setup,
> ontology starter, managed ingest, Git review/admission, exact-revision
> publication to a visible local Published Version, retrieval, traversal,
> citation opening, Source Artifact inspection — ending with a grounded agent
> answer. The optional S3 publication and Reader path is a separate guide:
> [`docs/howto-s3-publish.md`](howto-s3-publish.md). This guide is the
> reference the journey links into.

> Lumio's public foundation ships as two progressively enhanced wheels (the
> deployable `lumio` web application lives in a separate private repository
> and is not published from this one). This guide uses
> `lumio-wiki` (the portable, model-free foundation) unless noted — it works
> everywhere with no model provider, no LanceDB, no web server.

| Distribution | Installs | This guide section |
|---|---|---|
| `lumio-wiki` | Knowledge Base model, CLI, validation, search, traversal, ingest | [CLI](#1-cli) + [Python library](#2-python-library) + [Coding agent](#3-coding-agent-harness) |
| `lumio-lancedb` | `lumio-wiki` + LanceDB BM25/semantic/hybrid retrieval | [Enhanced retrieval](#enhanced-retrieval-optional) |

## Install

```bash
pip install lumio-wiki                       # foundation
pip install 'lumio-wiki[documents]'          # + PDF/image/office/HTML ingestion (LiteParse/AnyDoc/MarkItDown)
pip install 'lumio-wiki[llm]'                # + unattended OpenAI-compatible Distiller
pip install 'lumio-wiki[all]'                # documents + llm (still no LanceDB)
pip install 'lumio-wiki[s3]'                 # + S3-native KB Locations (ADR-0013)
pip install 'lumio-wiki[mcp]'                # + read-only MCP server over stdio (official SDK)
pip install lumio-lancedb                    # + enhanced BM25/semantic/hybrid retrieval
```

The base wheel depends only on `msgspec[yaml]` and `msgpack`. The full
`lumio` web application (chat UI, auth, roles, providers) is a separate
private repository and is not installable from this one.
Verify your install:

```bash
lumio-wiki --version         # lumio-wiki 0.5.0
lumio-wiki doctor            # version, detected extras, packaged skill path
```

---

## 1. CLI

The public CLI is `lumio-wiki` — the portable, model-free Knowledge Base
toolkit. (The `lumio` application CLI — cited answers, storage sync, the web
server — belongs to the separate private application repository; see the
boundary note at the end of this section.)

### One-command project setup

`lumio-wiki setup` wires a project directory so your agent harness knows where
the wiki lives and how to use it. It creates the Knowledge Base (or adopts an
existing one), writes `.env` with `LUMIO_KB_PATH`, writes/updates `AGENTS.md`
with the retrieval-ladder protocol, and optionally installs the packaged Agent
Skill.

```bash
cd my-project

# Existing wiki? Adopt it.
lumio-wiki setup ./wiki

# Brand-new project? Create a wiki and wire it up.
lumio-wiki setup ./wiki --agent claude-code --overwrite

# Skip the AGENTS.md section if you want to write it yourself.
lumio-wiki setup ./wiki --no-agents-md
```

After setup, `lumio-wiki` commands can omit the `<kb>` path because the CLI
reads `LUMIO_KB_PATH` from your environment or `.env`:

```bash
export LUMIO_KB_PATH=./wiki
# or source .env
lumio-wiki search "technology stack"
lumio-wiki page "Technology Stack"
```

### S3 coding-agent projects

The same `setup` command configures a project against object storage
(issue #161, ADR-0019) — there is no second configuration file; every setting
below is recorded in the project `.env` allowlist.

```bash
# Maintainer: local worktree + S3 publication destination + retrieval backend
# (+ optional private source artifact store), one command:
lumio-wiki setup ./knowledge-base \
  --publish-to s3://public-kb-bucket/team-kb \
  --retrieval lancedb \
  --source-store s3://private-source-bucket/team-kb \
  --skill-scope user

# Reader: read-only project against an existing S3 Knowledge Base Location:
lumio-wiki setup --from s3://public-kb-bucket/team-kb --retrieval lancedb
```

What setup records (and never more — `.env` loading is a bounded allowlist):

| `.env` key | Written by | Meaning |
|---|---|---|
| `LUMIO_KB_PATH` | both forms | Local KB path, or the read-only S3 Location URI for `--from`. |
| `LUMIO_PUBLISH_TO` | `--publish-to` | S3 publication destination; `publish-s3` reads it when no destination is passed. |
| `LUMIO_RETRIEVAL_BACKEND` | `--retrieval` | Retrieval *backend*: `zero-index` or `lancedb`. The retrieval *mode* (lexical/semantic/hybrid) stays a separate setting. |
| `LUMIO_SOURCE_STORE` | `--source-store` | Private Source Artifact Store (ADR-0020). Setup refuses to record it when `.env` is tracked by git. |
| `LUMIO_S3_REGION` / `LUMIO_S3_ENDPOINT` | never written by setup | Deployment connection settings; may live in `.env`, exported values win. Credentials are never written — standard AWS resolution applies. |

Notes:

- Optional capabilities are never installed for you. Missing `lumio-wiki[s3]`
  or `lumio-lancedb[s3]` fails setup with one exact command, e.g.
  `pip install 'lumio-wiki[s3]'` / `pip install 'lumio-lancedb[s3]'`.
- With no location in an interactive terminal, `lumio-wiki setup` runs a short
  wizard asking the same questions as the flags. Non-interactively it fails
  with the required flags instead of prompting.
- After reader setup, pathless commands read the active Published Version:
  `lumio-wiki search "query"` (no path, no local copy).
- Raw Source Artifacts are optional (retention is disabled by default) and
  private: the store never appears in the published Knowledge Base, and
  `source inspect`/`fetch`/`link` are authorized provenance review — not
  Evidence and not claim-level lineage.

### Git transport

`--from` also accepts a git clone URL (any value that does not start with
`s3://`). Setup runs `git clone <url> <target>` (the URL is passed as a
single argument, never through a shell), validates the clone as a Knowledge
Base, and records the clone as `LUMIO_KB_PATH`:

```bash
lumio-wiki setup --from git@github.com:acme/team-kb.git
# -> Read-only Knowledge Base cloned at ./team-kb
```

A missing `git` executable, a failed clone, or an invalid Knowledge Base each
fail with a bounded error; nothing is configured unless the clone is valid.
Update a cloned project with `git -C team-kb pull` (or re-run `setup --from`
after removing the clone).

The Git workflow uses an explicitly selected registered branch/worktree.
Adopt `.lumio-authoring.yaml` version 1 with a stable namespace and exact
Entity/Source/SHA-256 bindings; keep the private Source Registry, originals,
artifacts and transcripts outside Git/public content. Select the registry
with `--source-registry` or `LUMIO_SOURCE_REGISTRY`. Setup neither initializes
Git nor infers adoption. `ingest` edits ordinary files; review the full diff,
validate and commit. GitHub/PRs are optional. A commit or merge is not a
Published Version: preview the exact full commit, then confirm only after the
operator authorizes that displayed review, destination and expected current
version. Git is not required for plain reads, queries or validation.

| Lumio role | Git host (e.g. GitHub) | Lumio app | S3 IAM |
|---|---|---|---|
| Reader | read (clone/pull) | `READER` | read-only bucket policy |
| Maintainer | write (push branches, open/review PRs) | `MAINTAINER` | write objects, no pointer |
| Owner | admin (merge, protected branches) | `OWNER` | pointer/admin policy |

> **Warning — `.gitignore` is for `.env` only, never for KB content.** The
> loader reads every `*.md` under the Knowledge Base root regardless of
> `.gitignore`: a "private" page kept only out of git still gets searched,
> fingerprinted, and published. Personal content belongs in a separate
> personal Knowledge Base outside the shared root.

### lumio-wiki — portable Knowledge Base CLI

Works from any environment with no model provider and no LanceDB. `<kb>` is
the Knowledge Base root directory (or an `s3://` URI with `[s3]` installed).
If omitted, the CLI falls back to the `LUMIO_KB_PATH` environment variable.

```bash
lumio-wiki setup <kb-path> [--skill-scope user|project | --agent <name>]  # project bootstrap; skill target optional
lumio-wiki init <path>                       # lower-level KB-only: scaffold a categorized Knowledge Base
lumio-wiki validate <kb>                     # exit 0 if valid, 1 otherwise
lumio-wiki search <kb> "<query>" [--limit N] # lexical search over titles, aliases, tags, summaries, bodies
lumio-wiki page [<kb>] "<title>" [--raw|--json] # lossless or bounded page read
              [--section "<heading>"] [--line-start N] [--line-end N]
              [--max-lines N] [--max-bytes N]
lumio-wiki related <kb> "<title>"            # list pages related to a title
              [--scope canonical|discovery] [--direction outgoing|incoming|both]
              [--depth N] [--max-edges N] [--max-results N] [--trace]
lumio-wiki paths <kb> "<src>" "<dst>"        # shortest typed path between two titles
              [--scope canonical|discovery] [--max-depth N] [--trace]
lumio-wiki entity <kb> "<name>"              # resolve a stable Entity from an exact ID, title, or alias
lumio-wiki hot <kb>                          # Maintainer-pinned Hot Index (retrieval ladder step 0)
lumio-wiki index <kb> [dir]                  # generated Navigation Index (step 1)
lumio-wiki ingest <kb> <file> [--distiller passthrough|llm]   # ordinary Git worktree edits
lumio-wiki ingest <kb> <source> --compiled-page <page.md> --source-id <id>  # managed host-Distiller ingest (bind original source + authored page, issue #149)
lumio-wiki ingest-url <kb> <url> --compiled-page <page.md> --source-id <id> # safe URL ingestion (HTTPS-only, bounded, SSRF-safe; issue #178)
              [--max-bytes N] [--timeout S] [--max-redirects N]
              [--allow-http] [--allow-private-destination]   # explicit escape hatches for trusted local endpoints
lumio-wiki ingest-research <kb> <report.md> --manifest <manifest.yaml> --source-id <id>  # bounded research bundle (consulted URLs = provenance; issue #178)
lumio-wiki capture session <kb> --compiled-page <page.md> --manifest <capture.yaml> --source-id <id> [--transcript <path>] [--yes]  # explicit, preview-first session capture (issue #179)
lumio-wiki capture sessions --client codex|pi [--project PATH] [--since ISO] [--limit N]  # read-only past-session discovery
lumio-wiki capture export --client codex|pi --session-id <id> --output <empty-dir>          # read-only transcript + manifest export
lumio-wiki remove-page <kb> "<title>" [--reason <text>]       # stage an explicit Page Removal as worktree edits
lumio-wiki merge-entity <kb> <retired-id> <survivor-id> [--reason <text>]  # reviewed Entity Merge: retarget Claims/links, record redirect
lumio-wiki rename-page <kb> "<title>" --to "<new-title>" [--category <c>] [--alias ...]  # rename/recategorize/re-alias one page in the worktree
lumio-wiki publish <kb> --revision <full-commit-id> --to <dest> --expected-current <version-or-none> [--json]  # preview only
# Only after explicit operator authorization of that displayed review:
lumio-wiki publish <kb> --revision <full-commit-id> --to <dest> --expected-current <version-or-none> --confirm <review-digest> [--json]
lumio-wiki rollback <dest> --version <version> --expected-current <version-or-none> [--confirm <review-digest>]  # activate a complete local Published Version (preview/confirm)
lumio-wiki legacy-proposals inventory <kb> [--ingest-dir <private-store>]  # read-only inventory
lumio-wiki legacy-proposals export <kb> <id> --baseline <full-commit-id> --branch <name> [--confirm]  # unadmitted export
lumio-wiki lint <kb>                        # read-only cross-page QA report with graph scope disclosed
lumio-wiki cross-link <kb> [--stage]         # missing-link candidates (Extracted References); --stage repairs as links
lumio-wiki dream <kb> [--stage] [--semantic] # read-only Dream Cycle reflection; Source Drift diagnostics are
                                             #   advisory (never staged, never blocking, no exit-code change)
lumio-wiki export-graph <kb> [--scope public|all] [--out-dir <dir>]  # Discovery Graph to graph.json + graph.graphml
lumio-wiki import-graph <kb> <graph.json>   # apply stub pages from graph.json as ordinary Git worktree edits
lumio-wiki source list [<kb>]                    # list private Source identities (ADR-0014)
lumio-wiki source retire [<kb>] --source-id <id> # edit Git retirement intent; remaining support must validate
lumio-wiki source reactivate [<kb>] --source-id <id> --file <path> --entity <entity-id> # explicitly select all still-declaring Entities
lumio-wiki source resolve <kb> "<query>" [--published-version <v>] [--json]  # resolve a Source ID, Entity ID, page title, alias, or path to ONE registered Source (identity + availability; bounded candidates; never a signed URL)
lumio-wiki source inspect <kb> --source-id <id> [--published-version <v>]  # secret-free metadata for the exact bound Source Version (ADR-0020)
lumio-wiki source fetch <kb> --source-id <id> [--published-version <v>] --output <path>  # byte-exact original, digest/size re-verified (private, optional)
lumio-wiki source link <kb> --source-id <id> [--published-version <v>] [--expires 5m]  # short-lived exact-object signed GET URL (bearer secret; 1 h max)
lumio-wiki publish-s3 <kb> [dest] --revision <full-commit-id> --expected-current <version-or-none>
              [--confirm <review-digest>] [--retrieval lancedb] # same admission gate; build/health failure blocks activation
lumio-wiki rollback-s3 <dest> --version <historical-version> --expected-current <active-version>
              [--confirm <review-digest>]          # preview first; never rebuilds historical bytes
lumio-wiki cleanup-s3 <dest>                     # report inactive incomplete version prefixes
                                                  #   (interrupted builds); deletes nothing
lumio-wiki diff-s3 <dest> --from <version> --to <version> [--json]  # deterministic delta between two immutable S3 versions (read-only)
lumio-wiki health <kb> [--rebuild]           # page counts, validation, Discovery Graph health
lumio-wiki status [<kb>] [--json]            # effective config + retrieval state, one secret-free summary (#175)
lumio-wiki eval <kb> [--gold-set <f>] [--semantic [--model <name>]] [--json]  # recall@k per retrieval stage (#138)
lumio-wiki eval-ontology <kb> [--gold-set <f>] [--json]  # entity resolution / traversal / scope separation (#173)
lumio-wiki doctor                            # install shape: version, optionals, skill location
lumio-wiki skill install --scope user|project # explicit shared cross-client install
lumio-wiki skill install --agent <name>       # compatibility fallback: pi, hermes, codex, claude-code
lumio-wiki skill status [--scope user|project | --agent <name>] # read-only drift state
lumio-wiki skill update [--scope user|project | --agent <name>] # explicit atomic refresh
```

**Reading from S3.** Any read command (`validate`, `search`, `page`,
`related`, `paths`, `hot`, `index`) accepts an `s3://bucket/path` URI instead
of a local directory. S3 reads resolve one immutable Published Version through
the Location seam with zero-index retrieval. Credentials/region/endpoint come
from standard env vars:

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_REGION=eu-west-1
# For local S3-compatible endpoints:
export LUMIO_S3_ENDPOINT=http://localhost:8333
export LUMIO_S3_ALLOW_HTTP=1

lumio-wiki search s3://my-bucket/kb "technology stack"
```

**Quick example against a local KB:**

```bash
$ lumio-wiki validate products/lumio/tests/fixtures/valid
Knowledge base is valid.

$ lumio-wiki search products/lumio/tests/fixtures/valid "stack" --limit 3
## Technology Stack
summary: The technologies Lumio uses.
path:    technology.md
score:   260.0
matched: title, alias, tag, body

$ lumio-wiki related products/lumio/tests/fixtures/valid "Technology Stack" --scope discovery --trace
Architecture
# trace: scope=discovery direction=outgoing max_depth=1 max_edges=1000 max_results=50 returned=1
```

### MCP server

`lumio-wiki mcp <kb-path-or-s3-uri>` (requires `pip install 'lumio-wiki[mcp]'`)
serves ONE Knowledge Base Location over the Model Context Protocol on stdio
(official `mcp` SDK). Configure it in any MCP host with the plain stdio
command — for example:

```json
{
  "mcpServers": {
    "lumio-wiki": {
      "command": "lumio-wiki",
      "args": ["mcp", "/path/to/kb"]
    }
  }
}
```

The v1 tool surface (contract version 1):

| Tool | Answers |
|---|---|
| `search` | title/path/passage rows for a query (lexical, `limit` default 20). |
| `page` | one Compiled Page by Canonical Page Title or alias (`found: false` when absent). |
| `related` | sorted related titles with the requested scope/direction and bounds. |
| `paths` | shortest directed path between two titles (echoes scope/direction). |
| `hot` | the Maintainer-pinned Hot Index (`markdown: null` when no pins). |
| `index` | the root Navigation Index (the full page catalog). |
| `health` | validation, page, and graph state — derived in memory, never written. |
| `status` | bound Location, fingerprint, page count, retrieval state. |

The server is strictly read-only: no tool ever creates, modifies, stages, or
publishes Knowledge Base content, and every tool call resolves a fresh
immutable Snapshot, so a long-running host never sees stale state.
Diagnostics never create derived directories or materialize graph artifacts.
An `s3://` Location binds the same read-only surface (requires
`lumio-wiki[s3]`); region/endpoint/credentials resolve from the standard
`LUMIO_S3_*` / `AWS_*` environment rules — never from the URI, which must be
credential-free.

### lumio — application CLI (separate private repository)

Documented for boundary awareness only: the `lumio` CLI (Agent Runtime,
storage sync, `lumio serve` web server) is owned by the separate private
application repository (ADR-0025). It is not built, published, or tested
from this public foundation, and nothing here claims it is installable from
it. On top of `lumio-wiki` it adds:

```bash
lumio validate <kb-path>                          # exit 0 if valid, 1 otherwise
lumio retrieve <kb-path> "<query>" [--limit N]    # lexical/frontmatter/graph retrieval
lumio ask <kb-path> "<question>"                  # cited answer via the Agent Runtime
lumio sync <source> "<query>" --working-dir <path>  # sync a storage source, then retrieve
              [--kb-path <p>] [--ref <branch>] [--mode git|shared|hybrid]
```

Inside that application's own repository checkout, prefix with `uv run`:

```bash
uv run lumio ask products/lumio/tests/fixtures/valid "What technology does Lumio use?"
```

---

## 2. Python library

The `lumio_wiki` package is the portable, model-free Knowledge Base foundation.
The core operations the CLI exposes — load, validate, search, retrieve, ingest,
review, publish, and maintain — are public Python functions; CLI-only
orchestration commands such as `setup`, `skill`, and `doctor` compose several
of those primitives rather than mapping to a single call.

### Load, validate, search

```python
from lumio_wiki import load_knowledge_base, validate

# Load and validate
kb, report = load_knowledge_base("my-kb")
print(f"Pages: {len(kb.pages)}, Valid: {report.is_valid}")

# Validate without loading (returns just the report)
report = validate("my-kb")
if not report.is_valid:
    for issue in report.issues:
        print(f"  {issue.severity}: {issue.message}")
```

### Zero-index retrieval with Evidence + Citation + Trace

```python
from lumio_wiki import load_knowledge_base
from lumio_wiki.retrieval import ZeroIndexRetrieval

kb, report = load_knowledge_base("my-kb")
adapter = ZeroIndexRetrieval()

results = adapter.retrieve(
    kb.pages,                  # the pages to search
    "technology stack",        # query
    limit=3,
)

for r in results:
    ev = r.evidence
    cit = r.citation
    print(f"Title:    {ev.page_title}")
    print(f"Path:     {ev.page_path}")
    print(f"Score:    {r.score}")
    print(f"Snippet:  {r.snippet[:80]}")
    print(f"Trace:    {' -> '.join(s.name for s in r.trace.stages)}")
    print(f"Citation: {cit.page_title} ({cit.relative_path})")
```

Output:

```text
Title:    Technology Stack
Path:     technology.md
Score:    4.0
Snippet:  # Technology Stack ...
Trace:    search -> rank
Citation: Technology Stack (technology.md)
```

### Entity and Claim traversal, shortest paths, resolution

```python
from lumio_wiki import load_knowledge_base

kb, report = load_knowledge_base("my-kb")

# Related pages: accepted Claims (canonical) + Extracted References (discovery)
related = kb.related_pages(
    "Technology Stack",
    scope="discovery",       # or "canonical" (accepted Claims only)
    direction="both",        # outgoing, incoming, or both
    relationship_type="uses",  # optional: filter by Claim Predicate ID
)
# -> ['Architecture']   (Canonical Page Titles; identity is the Entity ID)

# Shortest directed path between two titles
path = kb.shortest_path(
    "Technology Stack",
    "Architecture",
    scope="discovery",
)
# -> ['Technology Stack', 'Architecture']

# Deterministic entity resolution: exact ID, title, alias, or merge redirect
resolution = kb.resolve_entity("entity:lumio")   # or a title / alias / retired ID
print(resolution.entity.id, resolution.matched_by)
```

Traversal is bounded and authorized: pass `candidate_titles` (the titles the
caller may see) and authorization is applied **before** endpoint resolution
and expansion. Only `accepted` entity-to-entity Claims traverse; `disputed`
and `superseded` Claims and Extracted References never masquerade as
accepted support (ADR-0021).

### Reading a page by Canonical Title or alias

Use `page [<kb>] "<title>" --raw` for lossless canonical Markdown. Add
`--section`, line bounds, or `--max-lines`/`--max-bytes` for a bounded read;
truncation and omitted ranges are reported. Add `--json` for stable page
identity and coordinates. Machine errors are nonzero, safe, and do not include
provider exceptions, credentials, registry data, signed URLs, or raw Sources.

```python
from lumio_wiki import load_knowledge_base

kb, report = load_knowledge_base("my-kb")
pages = kb.lookup_by_title("Technology Stack")  # exact title
aliased = kb.lookup_by_alias("Stack")            # by alias
page = pages[0]

print(page.title)           # "Technology Stack"
print(page.tags)            # ["technology", "stack"]
print(page.summary)         # "The technologies Lumio uses."
print(page.body)            # full Markdown body
print(page.path)            # "technology.md"
```

### Ingest workflow (you are the Distiller)

After explicitly adopting the Git authoring manifest and selecting the private
registry outside the repository:

```python
from pathlib import Path
from lumio_wiki import ingest_into_worktree
from lumio_wiki.source_registry import SourceRegistry

original = Path("/private/notes.md")  # not tracked by the KB repository
result = ingest_into_worktree(
    "my-kb", original.read_bytes(), "text/markdown", original.name,
    "notes", authored_markdown,  # page declares sources[].id = notes
    source_registry=SourceRegistry("/private/source-registry"),
    raw_source_path=original,
)
```

The helper registers exact private bytes and validates/writes ordinary page
and manifest files. It never commits or publishes. Review with native Git,
commit the complete candidate, then use separate preview/confirm admission.
Registering B does not change an existing binding to A or historical Evidence.

### Use myKG as an experiment-only upstream extractor

Lumio can evaluate [myKG](https://github.com/SenolIsci/mykg) as an out-of-process,
corpus-level extractor. This is an experiment harness, **not** a runtime
integration: myKG is not a `lumio-wiki` dependency, its output is never
canonical by itself, and every imported page or Claim still passes
through complete-candidate validation and explicit Publication Admission.

Before a real run, choose a private corpus, pin the myKG version and
model/provider configuration, set a cost/time budget, and choose a private
artifact directory. The complete runbook and blank evaluation report are in
[`experiments/mykg/`](../experiments/mykg/README.md).

Convert an existing myKG session—or try the included synthetic sample—into a
temporary Compiled Markdown tree:

```bash
uv run python products/lumio/experiments/mykg/convert_mykg.py \
  --session products/lumio/experiments/mykg/sample \
  --out /tmp/mykg-candidates \
  --default-lifecycle review \
  --default-visibility internal
```

The output contains candidate pages plus private
`relationship-candidates.jsonl` and `conversion-report.json` sidecars. The
converter never writes extracted edges into page `claims:` frontmatter.

Deterministic serialization: all Entity/Claim/Ontology records are frozen
`msgspec.Struct`s whose fields serialize in stable declaration order, and
`lumio.yaml` (including its `ontology:` section) is written with sorted keys
and a stable section order — identical canonical content always produces
byte-identical files and therefore stable fingerprints.
Inspect the parsed candidate provenance and diagnostics before explicitly
writing the selected Git worktree:

```python
from lumio_wiki import import_external_compiled_markdown, write_pages_into_worktree

parsed = import_external_compiled_markdown("/tmp/mykg-candidates")
# Review parsed diagnostics and each page's explicit Sources first.
result = write_pages_into_worktree("my-kb", parsed.proposed_pages)
```

Review the complete Git diff, validate and commit before separate admission.
Review the private relationship sidecar separately; never publish the raw
corpus, myKG session files, confidence values, source paths or private sidecars.

### Publishing to S3 (immutable Published Versions)

Use the same exact-revision admission gate as local publication:

```bash
lumio-wiki publish my-kb --revision <full-commit-id> --to s3://bucket/kb \
  --expected-current <version-or-none> --source-registry <private-dir>
# Only after the operator authorizes the displayed review:
lumio-wiki publish my-kb --revision <full-commit-id> --to s3://bucket/kb \
  --expected-current <version-or-none> --source-registry <private-dir> \
  --confirm <review-digest>
```

The SDK equivalents are `preview_publication` / `publish_revision` with an
explicit `S3Location`, effective target identity and private metadata store.
All requested artifacts and exact historical bindings are verified before
conditional activation; an index failure or CAS conflict preserves old readers.

### Reading from an S3 Location

```python
from lumio_wiki.s3_location import open_s3_knowledge_base

# Resolve one immutable Published Version from S3 (requires lumio-wiki[s3])
snapshot = open_s3_knowledge_base(store, prefix="kb")
# snapshot.pages          — all Compiled Pages
# snapshot.fingerprint    — SourceFingerprint of this version
# snapshot.knowledge_base — KnowledgeBase instance for traversal/search

# Or open a specific version:
snapshot = open_s3_knowledge_base(store, prefix="kb", version="2024-01-15")
```

### Key public types

```python
from lumio_wiki import (
    # Core model
    KnowledgeBase, CompiledPage, KnowledgeBaseControlFile,
    # Validation
    ValidationReport, ValidationIssue, validate,
    # Records (immutable msgspec structs)
    RetrievalResult, Evidence, Citation, RetrievalTrace, TraceStage,
    PageSearchResult, Relationship, ExtractedReference,
    SourceFingerprint, GraphState,
    # Entity-claim ontology (ADR-0021)
    Entity, EntityTypeDefinition, Claim, ClaimEvidence, EntityRedirect,
    EntityResolution, EntityResolutionCandidate,
    # Location seam
    KnowledgeBaseLocation, KnowledgeBaseSnapshot,
    FilesystemLocation, open_filesystem_knowledge_base,
    # S3 (requires lumio-wiki[s3])
    S3Location, open_s3_knowledge_base,
    # Git authoring and explicit publication admission
    ingest_into_worktree, write_pages_into_worktree,
    preview_publication, publish_revision, PublicationReview, PublicationReceipt,
    # Retrieval
    ZeroIndexRetrieval, RetrievalAdapter, default_retrieval_adapter,
    # Publish
    S3PublicationConflict,
    # Discovery Graph diagnostics
    StructuralGraphReport, GraphHealthReport,
    # Cross-link candidates
    LinkCandidate, RankedLinkCandidate, find_link_candidates,
)
```

---

## 3. Coding agent harness

Lumio works as a **shell-callable CLI** from any coding-agent harness that can
run commands. The packaged **Agent Skill** (`SKILL.md` + `PROTOCOL.md`) gives
the agent a structured protocol for the retrieval ladder, ingest workflow, and
guardrails.

### Install and maintain the Agent Skill

The wheel is the canonical skill contract. Installation is always explicit;
installing `lumio-wiki` or running ordinary `setup` never writes into an agent's
instruction directories.

Prefer the shared cross-client user scope:

```bash
lumio-wiki skill install --scope user
# ~/.agents/skills/lumio-wiki/

lumio-wiki skill status --scope user
lumio-wiki skill update --scope user
```

A trusted repository may instead opt into a project-local copy:

```bash
lumio-wiki skill install --scope project
# ./.agents/skills/lumio-wiki/
```

Project scope travels with the checkout and is therefore part of that
repository's instruction trust surface. Review it like other executable agent
instructions. Each copy contains a manifest with the distribution version and
bundle hash; `status` reports `missing`, `current`, `stale`, or `corrupt`, and
`update` performs an explicit atomic refresh.

### opencode (or any agent that runs shell commands)

opencode doesn't have a native "skill" concept, so you configure it via
**custom instructions** (the project `AGENTS.md` or `.opencode` config). The
fastest path is `lumio-wiki setup`, which writes both `.env` and `AGENTS.md`
for you:

```bash
cd my-project
lumio-wiki setup ./wiki
# or explicitly request a shared project/user skill install:
# lumio-wiki setup ./wiki --skill-scope project
# lumio-wiki setup ./wiki --skill-scope user
```

This writes `LUMIO_KB_PATH=./wiki` to `.env` and a `## Lumio Knowledge Base`
section to `AGENTS.md`. In opencode, point the agent at that file (or paste
the relevant section into `.opencode` settings):

**Option A — `AGENTS.md` (project-level, version-controlled, auto-generated):**

```markdown
## Lumio Knowledge Base

This project uses a Lumio Knowledge Base for domain knowledge. The host coding
agent IS the default Distiller (no model provider needed for base ingestion).

**KB path:** `./wiki` (also in `.env` as `LUMIO_KB_PATH`; the CLI reads it
automatically when no `\u003ckb\u003e` argument is given).

### Retrieval ladder (cheapest-first, stop when you have Evidence)

0. `lumio-wiki hot` — Maintainer-pinned entry pages. Read first.
1. `lumio-wiki index [dir]` — generated Navigation Index (all pages by directory).
2. `lumio-wiki search "\u003cquery\u003e"` — zero-index lexical search (no external index).
3. `lumio-wiki page "\u003ctitle\u003e"` — read a page to confirm and cite the exact passage.
4. `lumio-wiki related "\u003ctitle\u003e" --scope discovery` — related pages (canonical + extracted).
5. `lumio-wiki paths "\u003csrc\u003e" "\u003cdst\u003e"` — shortest directed path between two titles.

### Ingest (you are the Distiller)

1. Explicitly select/adopt a Git authoring worktree and private Source Registry.
2. Author a Compiled Page, then `lumio-wiki ingest <file>` writes ordinary files.
3. Review the full Git diff, validate the complete candidate and commit.
4. Preview `publish --revision <full-commit-id> --to <dest> --expected-current
   <version-or-none>`; confirm with its review digest only after operator authorization.

### Guardrails

- **Cite or refuse.** Every domain claim cites a Compiled Page (title + path +
  passage). Unsupported claims return "not covered by this knowledge base."
- **Connectivity is not support.** Graph reachability selects pages to inspect;
  it never manufactures Evidence.
- **Git authoring, explicit admission.** Validate the complete candidate and
  review/commit with Git. A commit or general coding request never authorizes
  confirmation of publication.

### Diagnostics

- `lumio-wiki doctor` — version, detected extras, skill location.
- `lumio-wiki health` — page counts, validation, Discovery Graph health.
- `lumio-wiki status [<kb> | --json]` — effective configuration + retrieval state: project role, location and its configuration source, active Published Version (S3), retrieval backend/mode as separate fields, graph source, LanceDB health with fallback reasons, Source Artifact retention, validation, one next action (#175).
- `lumio-wiki validate` — exit 0 if valid, 1 otherwise.
```

**Option B — `.opencode` custom instructions:**

In your opencode project settings, paste the same block (or reference the
project `AGENTS.md`). The key is telling the agent that `LUMIO_KB_PATH` is set,
so it can run `lumio-wiki search "authentication"` without hardcoding the
path every time.

**Option C — direct shell calls (no config needed):**

opencode can run shell commands. If `lumio-wiki` is installed (`pip install
lumio-wiki`), the agent simply calls it. With `LUMIO_KB_PATH` exported in
the shell or `.env`, the path is implicit:

```bash
# Find pages about a topic
lumio-wiki search "authentication"

# Read the relevant page
lumio-wiki page "Authentication Architecture"

# Check related pages for broader context
lumio-wiki related "Authentication Architecture" --scope discovery --trace
```

### Claude Code / Codex / Pi / Hermes

Use shared user scope when the client scans `.agents/skills`. Client-specific
compatibility destinations remain available as explicit fallbacks:

```bash
lumio-wiki skill install --agent claude-code   # ~/.claude/skills/lumio-wiki/
lumio-wiki skill install --agent codex         # ~/.codex/skills/lumio-wiki/
lumio-wiki skill install --agent pi            # ~/.pi/agent/skills/lumio-wiki/
lumio-wiki skill install --agent hermes        # ~/.hermes/skills/lumio-wiki/
```

Restart the agent or start a new session after installation or update so the
client discovers the refreshed `SKILL.md`.

### FAQ: how does the agent harness know where the wiki is?

**If the wiki already exists:** run `lumio-wiki setup ./wiki`. This writes
`.env` with `LUMIO_KB_PATH=./wiki` and `AGENTS.md` with the retrieval ladder.
The agent reads the path from `.env` (or you paste it into `.opencode`
settings), and the `lumio-wiki` CLI resolves it automatically when no
`\u003ckb\u003e` argument is given.

**If the wiki doesn't exist yet:** run `lumio-wiki setup ./wiki`. It creates
an empty categorized Knowledge Base (`lumio.yaml` + `.lumio/index`)
writes `.env` and `AGENTS.md`, and installs no skill unless an explicit
`--skill-scope` or `--agent` target is supplied. Add your first `.md` Compiled Pages under `./wiki`,
then `lumio-wiki validate`. The setup is idempotent: re-running it on an
existing KB only updates `.env`, `AGENTS.md`, and the optional skill install.

### Ingest from a coding agent

The host coding agent is the default **Distiller** — no model provider needed.
Author the Compiled Page Markdown, write it to a temp file, then:

```bash
# In an explicitly selected/adopted Git worktree:
lumio-wiki ingest ./kb /tmp/new-page.md
git -C ./kb diff
lumio-wiki validate ./kb
git -C ./kb add <authored-paths> .lumio-authoring.yaml
git -C ./kb commit -m "Review knowledge change"
lumio-wiki publish ./kb --revision <full-commit-id> --to <dest> --expected-current <version-or-none>
# Only after operator authorization: repeat with --confirm <review-digest>.
```

For unattended distillation (no human-authored Markdown), install
`lumio-wiki[llm]` and pass `--distiller llm`.

### Guardrails (enforced in every harness)

- **Cite or refuse.** Every domain claim cites a Compiled Page (title + path +
  passage). Unsupported claims return "not covered."
- **Connectivity ≠ support.** Graph reachability selects pages to inspect; it
  never manufactures Evidence.
- **Git authoring, explicit admission.** Validate the complete candidate and
  review/commit with Git. A commit or general coding request never authorizes
  confirmation of publication.
- **Public surface only.** The protocol invokes only the public CLI and Python
  API. It never parses the private MessagePack graph artifact or starts the
  web application.

---

## Enhanced retrieval (optional)

Install `lumio-lancedb` for BM25, semantic, and hybrid ranking over the same
Knowledge Base. The RetrievalResult / Evidence / Citation / Trace contract is
identical to zero-index — only the ranking quality changes.

```bash
pip install lumio-lancedb                        # + LanceDB + PyArrow
pip install 'lumio-lancedb[embeddings]'          # + sentence-transformers for local embeddings
```

```python
from lumio_lancedb import LanceDBRetrievalAdapter

adapter = LanceDBRetrievalAdapter()
results = adapter.retrieve(kb.pages, "how does authentication work?", limit=5)
# Same RetrievalResult contract as ZeroIndexRetrieval
```

The separate private `lumio` app selects zero-index or LanceDB retrieval via
`LUMIO_RETRIEVAL_BACKEND` (its default is `lancedb`); the public foundation's
zero-index retrieval needs no configuration. Switch without code changes —
just install/uninstall the adapter and flip the env var.

### Scoring a real embedder in `eval`

`lumio-wiki eval --semantic` measures recall@k for the semantic/hybrid stages.
Without `--model` it uses a deterministic, offline hash embedder (no provider,
no network) so the run stays hermetic and CI-stable. Pass `--model` to score a
real embedding model — the same resolver `search --model` uses, so eval and
search share provider-first / local-fallback behavior:

```bash
lumio-wiki eval <kb> --gold-set gold.yaml --semantic                          # deterministic hash embedder (offline)
lumio-wiki eval <kb> --gold-set gold.yaml --semantic --model all-MiniLM-L6-v2  # local sentence-transformers (lumio-lancedb[embeddings])
LUMIO_PROVIDER_BASE_URL=… LUMIO_PROVIDER_API_KEY=… \
  lumio-wiki eval <kb> --gold-set gold.yaml --semantic --model text-embedding-3-small --json  # OpenAI-compatible /embeddings; JSON names the model used
```

The JSON report (and table) carry an `embedder` field naming the model that
scored the run (`lumio-eval-deterministic-hash` for the stand-in), so a
reviewer can tell the hash stand-in from a real model at a glance (#158).

---
