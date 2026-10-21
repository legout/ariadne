# Changelog

## Unreleased

## 0.6.1 - 2026-10-21

- Relocate Core into the monorepo as `packages/ariadne-data` inside the
  coordination-only root uv workspace; the distribution name, import roots,
  CLI entry points, optional `mcp`/`documents` extras and Python >=3.14 are
  unchanged. Independent use remains first-class: base Core works without
  the Lumio SDK and without the optional MCP transport; the LanceDB adapter
  stays an optional SDK-side extra. The separately distributed Agent/Tau
  stack and the repository rename are excluded from this release.
- Repair relocated local/Git documentation and example paths, and align the
  same-commit development CI (joint Core+SDK wheel pairing, member-scoped
  lint via the existing dev extra, native test selection with the original
  prepared-S3 exclusions).
- Release qualification pairs Core with the exact published public producer
  wheel `lumio-wiki==0.4.1` (immutable PyPI URL and SHA-256 recorded in the
  release workflow), producer-first; the previously qualified 0.6.0/0.4.0
  tutorial baseline remains the tested numerical example.
- Bound the DuckDB runtime dependency to `duckdb>=1.0,<2`: DuckDB 2.0.0
  (published 2026-10-21, immediately before release CI) removes the relation
  `fetchmany`/`fetchone` APIs the unchanged engine uses, so Core keeps the
  existing 1.x compatibility family; no other dependency changed. No new
  runtime feature, numerical attestation or re-admission shortcut; governance
  and admission semantics are unchanged.
  Canonical release tag: `core-v0.6.1` in the current public `legout/ariadne`
  repository (candidate preparation — Core is not yet published).

## 0.6.0 - 2026-10-21

- **Git/local-first operation** — report the exact local Git HEAD separately
  from the verified admitted Bound Release, Published Version and supported
  operations. Sync never activates a release or repins an existing session;
  the ordinary reconcile/validate/review/overall-confirm chain remains required.
- **Scoped immutable knowledge navigation** — source-free discovery and
  `search-context`, plus the existing MCP/Agent page tools, preserve SDK page
  identity, full canonical content, citations, native ranking and verbatim
  passages. Hidden and unknown paths refuse without hidden-content disclosure.
- **Governed multi-metric queries** — resolve complete per-metric Policy closure
  and the shared pinned context before planning or execution; required context
  that cannot fit refuses the whole operation without dropping content.
  `list-datasets` retains its source-approved live-catalog behavior.
- **Technical References and term resolution** — validate every captured
  Reference through native Core citation/evidence rules, including hidden pages.
  Reuse one resolver for exact bindings, ambiguity, freshness and exact human
  mapping confirmation; measured authority uses authentic Core receipts, while
  manual source-backed assertions retain their existing native eligibility.
  Policy changes invalidate dependent evidence; escaped KB citations cannot
  become captured bundle evidence. Resolution grants no SQL/join authority.
- **Bounded adapters and public guidance** — oversized required discovery
  content refuses as a whole, and source-free MCP tools reject unusably small
  refusal ceilings. Keep optional MCP guidance in its optional skill section.
- **Release pairing** — optional integrated use pairs `ariadne-data==0.6.0`
  with `lumio-wiki==0.4.0`. Base Core remains SDK-independent. Changed software
  builds require genuine revalidation and a fresh matching admission.
  Python remains >=3.14; Agent/Tau, ad-hoc integrated operations and Core KB
  bindings over S3 remain excluded. Admission is not numerical attestation.

## 0.5.0 - 2026-10-19

- **ODCS contract consumer (#75, #77, #78)** — consume the official ODCS
  3.2.0 schema through the supported flat contract profile, Git-native model
  bindings and bounded source-approved observations. Contract metadata is
  disclosed through existing surfaces; unsupported checks never imply conformance.
- **Local Lumio-bound Metric MVP (#81)** — one authored Git revision combines
  Core models/contracts and `knowledge/`. Human composite admission binds exact
  native validation, source approvals, immutable local SDK publication, Visibility
  Scope and actual build contents. `get_metric` returns the full required Metric
  and Policy context, exact citations and existing caveats; admission does not
  create independent numerical attestation.
- **Strict integrated capability boundary** — supported Metric/Policy profiles
  are validated globally; unsupported technical annotations and integrated
  Analyst operations refuse instead of falling back. `discover`/`list_metrics`
  disclose the admitted catalog without source execution. Standalone behavior
  remains SDK-independent. Integrated KB bindings over S3 and broader operations
  remain deferred; native Core source/storage capabilities are not removed.
- **Evidence and compatibility fixes** — validation binds the build that ran it,
  including applicable retained observations; a changed build requires genuine
  revalidation. Standalone initial authoring ignores unrelated knowledge symlinks.
- **Core-only release** — publish `ariadne-data` only. `ariadne-agent` and
  `tau-mcp` are not changed or released. The optional integration pairs with
  `lumio-wiki==0.3.0`; Python remains >=3.14.

## 0.4.1 - 2026-10-16

Hotfix: the released `ariadne-agent` 0.4.0 was incompatible with
`ariadne-data` 0.4.0.

- **Agent migration to the Git-only core (#73 remainder)** — embedded Agent
  sessions now resolve through the core project factories
  (`QueryRuntime.open_project` / `DiscoveryRuntime.open_project`) using the
  server's deferred first-admission pattern: a not-yet-admitted project opens
  an Analyst session with source-free discovery, the first governed query
  refuses honestly naming the human-only `ariadne-admit` step, and the first
  real admission is picked up once and stays pinned. The retired direct
  runtime construction (`staging_dir`, artifact roots) and all
  Promotion/staging guidance are gone; `define_metric` guidance reports the
  ephemeral `persistence: not_saved` result. The authoring `upload_document`
  tool is removed with the retired core seam — originals are operator-placed
  external inputs. Agent tests migrated to real Git admission fixtures (34
  cases, Python 3.14 with `tau-ai==0.4.6` and `tau-mcp 0.1.0`); the packaged
  agent README now documents the Git-only session contract. Core is
  unchanged; live-model behavior remains unverified.

## 0.4.0 - 2026-10-16

Fifth release: Git-only durable authoring (#74) on the Python 3.14 / MCP 2.2.0 core (#73).

- **Core Python 3.14 and MCP 2.2.0 (spec 0026, #73)** — `ariadne-data` now
  requires Python >=3.14 (the floor change ends 3.12/3.13 support; scoped
  ADR-0008 amendment) and pins the optional `mcp` extra and development
  environment to the official `mcp==2.2.0` SDK (with `mcp-types==2.2.0`),
  the same resolved release as the pinned Lumio Wiki integration baseline.
  The adapter serves the identical toolsets, schemas and error contracts on
  `MCPServer` (stdio default; opt-in Streamable HTTP keeps the bearer gate,
  loopback-only default with the explicit private-container exception, and
  DNS-rebinding protection). Docker, CI and Ruff now target Python 3.14.
  Ariadne Agent and Tau/tau-mcp are explicitly deferred: their files, pins
  and compatibility with this Core remain unchanged and unverified until
  that later work; the original complete #73 is not closed by this change.
- **Git-only durable authoring (spec 0027, ADR-0024, #74)** — Git is the only durable
  revision model for authored state. Ad-hoc `define_metric` execution is ephemeral
  (`persistence: {status: not_saved}`, no staging writes); retention goes through
  explicit revision-checked Authoring edits into unadmitted candidates. Answer
  Examples live in `answer_examples/` inside the same candidate snapshot and become
  reusable methods only through common human Git Review Admission; default search
  stays admitted-only, with explicit unadmitted candidate browsing. Ingestion writes
  derived pages/provenance into a named candidate (`--project`, `--proposal`,
  `--expected-revision`) while original documents remain external operator-managed
  inputs with digest-bound references verified at validation (validator v6). Legacy
  staging/Promotion/migration routes, the separate Example review, direct-root serving
  and their console entry points (`ariadne-author`, `ariadne-promote`,
  `ariadne-example-review`) are removed: public query/discovery construction is
  project-bound with exact human admission (no plain-root or mutable-candidate
  fallback), `ariadne-validate` is compile-only static checking, and
  `ariadne-init`/`ariadne setup` scaffold Git-first without running `git init` or
  granting source access. Breaking, new-project-only cleanup: there is no legacy
  migration/export tooling; operators arrange new projects and private originals
  themselves. Shared #76 interfaces remain unapproved.
- **Packaging** — `ariadne-agent` 0.4.0 aligns its Python floor to `>=3.14` with the
  core it ships alongside; the agent's runtime compatibility with the new core
  remains deferred and unverified (#73), and publishing still tests the core wheel
  only.

## 0.3.1 - 2026-10-14

Fourth release: named S3 storage profiles with environment-referenced
credentials, Lakehouse qualification, and a Diátaxis documentation
restructure.

- **Named S3 storage profiles (spec 0025, ADR-0023, #71)** — declarative,
  credential-free `storages:` profiles reference environment variables for
  keys, endpoints, region, and session token; sources select a profile and
  must stay inside its non-intersecting `s3://` scopes. The shared builder
  installs temporary URI-scoped DuckDB secrets per connection (values never
  in YAML, plans, or errors — including SQL-escaped forms), refuses
  ambient-secret shadowing, and freezes the effective binding into source
  approval, validation evidence, review/admission identity, and legacy
  staging/Promotion: an endpoint change needs a new human grant and fresh
  evidence, while key rotation alone does not. Profile-free registries and
  old records keep their existing shape and digests.
- **Lakehouse through named profiles (spec 0025 S2, #72)** — Delta, file-based
  Iceberg, and DuckLake (local metadata catalog + remote S3 data, attached
  `READ_ONLY`, no `DATA_PATH` override) qualified against two independently
  credentialed endpoints through the same builder, with actual extension
  versions asserted in the test suite.
- **Onboarding for multiple storages (#72)** — a Diátaxis how-to with shell
  and Docker examples, a commented scaffold template block, `.env.example`
  entries, and agent guidance; examples are validated against the real
  registry validator.
- **Documentation restructure** — the README is now a short overview and the
  guides follow Diátaxis under `docs/` (tutorial, how-to guides, reference,
  explanation), with the legacy-to-Git mappings pinned in the reference
  pages and the release quickstart folded into the tutorial.
## 0.3.0 - 2026-10-13

Third release: usability, verbatim ingestion, trusted sources, and context routing.

- **Usability & onboarding (#62–#65, specs 0016–0019, ADR-0021)** — read-only `status`
  project readiness diagnostics with explicit legacy-selector handling and
  corrupt-catalog detection (#62), a `setup` operator onboarding wizard that
  preserves routes and completed source approvals (#63), artifact-only unified
  discovery across analyst surfaces with isolated catalog read failures (#64),
  and an operator-only human review walkthrough (#65).
- **Verbatim ingestion (spec 0021, #66)** — opt-in verbatim document preservation,
  with honest retry matching across gaps and malformed drafts and exact
  serialized-timestamp masking.
- **Sources (spec 0022, #67)** — native DuckDB catalogs and trusted remote view
  catalogs, with dotted native schemas kept as one identifier and correct
  quoting of catalog/schema parts in SQL references.
- **SQL provenance (spec 0023, #68)** — every confirmed answer-example save
  retains `result.sql`; search exposes it only with `include-sql`; MCP save
  guidance shows the exact SQL before saving.
- **Context routing (spec 0024, #69/#70)** — reviewed Context Routing Map with
  type-bound selected observed filter values end to end and atomic
  artifact-bound refusal, plus skill-led Business Onboarding guidance.

## 0.2.0 - 2026-10-12

Second release: from the governed-metrics MVP to the full agent-facing platform.

- **Own compile engine, AGPL exit** — the `datus-semantic-osi[metricflow]` stack is
  gone; metric compilation is now an own SQLGlot-based engine (`ariadne/render.py`,
  ADR-0008). Runtime dependencies are permissive (MIT/Apache) only, and the Python
  floor is `>=3.12`.
- **Ariadne Agent** — new companion distribution `ariadne-agent` (ADR-0018):
  installable Analyst conversation over native Ariadne tools (#23), authoring
  sessions with human-only approval gates (#24), role-restricted stdio MCP
  integration (#25), and automatic mapping-hypothesis capture with restart-readable
  evidence (K5, #45).
- **Harness-led authoring (bring your own agent)** — isolated Git proposals with
  revision-checked complete artifact edits (#34), resolved-source approval and
  measured inputs (#35), finalized effective-revision validation with bounded review
  (#36), human-only Git Review Admission with pinned digest confirmation (#37), and
  safe legacy import with transition guidance (#39).
- **Three MCP toolset surfaces** — Analyst/Authoring/combined registrations over one
  shared core, selected per entry point (#38); context page browsing via
  `list_context_pages`/`read_context_page` (spec 0015, #60/#61).
- **Multifact semantic layer** — normalized single validated OSI graph (#26), fact
  branches aggregated before alignment (#27), scoped filters, typed parameters and
  grain-safe detail (#28), aligned time/compute derived windows (#29), and local
  graph bundles exposed via CLI/MCP (#30).
- **Context layer** — qualified schema facts with deterministic explicit refresh
  (K1, #41), extension-v1 references and scoped term resolution (K2, #42), typed
  bounded identifier inspection (K3, #43), context-only admission (K4, #44),
  explicit legacy enrichment and installed-candidate verification (K6, #46),
  `context_signals` disclosure (#48) with freshness fix (#47), bounded record/result
  queries (spec 0014, #56–#58), supplied-evidence caveats on answers (#54/#55), and
  answer examples with operator-only review (#19–#21).
- **Document ingestion** — proposal-first ingestion of PDF/Office/HTML data
  dictionaries (ADR-0009) with symlink refusal and secret scanning.
- **Source registry** — declarative multi-source registry with a shared connection
  builder (ADR-0010): strict schema, DSN redaction, explicit argument precedence.
- **Context-carrying answers + packaged agent skill** — unmodeled questions capture
  reusable working context into a self-improving catalog; `ariadne-skill` packages it
  (spec rev 10, ADR-0011).
- **HTTP transport + deployment** — opt-in local-only bearer-token streamable-HTTP
  (`ariadne-serve --http`, #18), container/Compose binding with `healthz`/`readyz`
  probes, and Docker/Compose templates for external MCP projects.
- **Security fix: declared-grain SQL injection in validation** — a staged model's
  `primary_key` entries were interpolated raw into the executed grain-audit
  statement (`validate.py` Assertion 1), so agent-authored YAML could run
  arbitrary DuckDB SQL (e.g. `COPY ... TO`) during `validate_proposal`/
  `ariadne-validate`, before any human review. Key entries must now parse as
  plain column references and are re-rendered by sqlglot; the assembled audit
  statement is proven single before execution. Regression test included.
- **Grain guard re-checks live data on every `get_metric`** — the per-process
  memo meant an ETL reload introducing join fan-out under a long-lived
  `ariadne-serve` session was never caught until restart.
- **No implicit demo-database fallback** — `ariadne`/`ariadne-serve` without
  `--sources`, `--db` or an ambient `ariadne.yaml` now refuse explicitly
  instead of silently querying `examples/retail-demo/data/demo.db`.
- **Cleanup** — removed the dead `proposals.stage_ad_hoc` wrapper (superseded
  by the reserve/stage/release split) and an unused authoring helper;
  repo-wide `ruff format` pass.
- **Packaging** — first PyPI release. The distributions are `ariadne-data`
  (core) and `ariadne-agent`; `ariadneai` was rejected by PyPI's name-
  similarity rule (the unrelated `ariadne-ai` project blocks it), so the
  owner re-scoped the names (ADR-0018, amended). Publishing is tag-gated
  via `publish.yml` with the core wheel tested before upload.

## 0.1.0 - 2026-09-17

First release: the governed-metrics MVP for autonomous agents.

- **Authoring agent** — profiles a database, combines with human seed notes, drafts the
  full OKF context bundle + OSI semantic models; ≤3-round compile-feedback loop; writes
  only to `staging/`.
- **OKF v0.2 context bundle** — tables, join references (cardinality + grain-safety
  notes), policies extracted from seed notes, governed metrics, attested computations
  (attester = eval harness), operational skills; `index.md` per directory + `log.md`.
- **MCP facade (five tools)** — `list_metrics` (dimensions + routing hint),
  `list_datasets`, `search_context` (served + draft-marked staged), `get_metric`
  (governed, provenance SQL), `define_metric` (ad-hoc: grain-checked, compiled,
  read-only, auto-staged proposal).
- **No-unvalidated-execution invariant** — no path from tool arguments to execution
  bypassing the compile gate + single-statement guard.
- **Grain governance** — shared join-uniqueness guard (CTE-aware) at both the facade
  and authoring boundaries; audit assertions (declared-grain uniqueness, parent
  aggregate invariance) in `validate.py`; ADR-0006 resolution rubric.
- **Promotion gate** — `promote.py`: merge-only, `verified` trails, index regeneration,
  idempotent.
- **Eval harness** — golden question→value sets; fan-out trap sentinel
  ([Datus-ai/Datus-agent#1426](https://github.com/Datus-ai/Datus-agent/issues/1426)).
- **Packaging** — console scripts (`ariadne-author/validate/serve/promote/init`),
  `ariadne-init` project scaffolder (symlink-safe), `.env.example`.
- **Demo** — deterministic synthetic dataset (status-exclusion + EMEA currency gotchas),
  `demo.sh` end-to-end.
