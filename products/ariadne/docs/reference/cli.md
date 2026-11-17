# CLI reference

This reference describes the Git-only Core interfaces. Examples assume commands run from a project root; use an explicit project path when running elsewhere.

## Project setup and route

`ariadne-init DIR` scaffolds a new project. It writes Seed Notes, the source-registry template, an operator pointer page and ignore rules. It does not initialize or configure Git, approve sources, admit a revision, or import existing staged state. `--with-mcp` opts into an MCP config; `--force` only overrides the project-manifest check and never overwrites existing scaffold files.

Configure Git yourself, then start a revision-checked proposal with `ariadne-authoring start --project DIR`. Durable project queries are project-bound and require a valid human admission:

```bash
ariadne status --project .
ariadne list-metrics --project .
ariadne get-metric gross_margin --project .
```

There is no plain-root serving route. The former `--served`, `--sources` and `--db` query selectors, staged bundle workflow, Promotion and legacy import/enrichment commands are not supported.

`ariadne setup --project DIR [--namespace NAMESPACE --private-profile PROFILE]` is read-only with respect to authority and Git configuration: it inspects filenames and prints operator handoffs. A fresh project is initialized only through the explicit `--namespace`/`--private-profile` selections (delegated once to the public initializer; the machine-local profile stays outside the repository), and an existing native Knowledge Base resumes by metadata validation, never reinitialization; conflicting selections refuse. It never runs `git init/config`, opens a source, approves sources, or admits. `ariadne status --project DIR [--json]` reports Git prerequisites, proposals, source approval, admission, and readiness without connecting to sources. `ariadne review --project DIR [--proposal ID]` is an operator walkthrough for one Git proposal; without an ID it lists pending proposals. A terminal prompt does not establish authenticated human identity.

Use [Getting started](../tutorials/getting-started.md) for a current native project.
The [historical joint tutorial](../../../../integration/docs/tutorials/lumio-ariadne-local.md)
retains the older Core 0.6.0 / SDK 0.4.0 example only.
Availability of the commands below is frozen by the admission's explicit
support revision, not by selector presence. See the exact supported set in
[Bound Releases](../../../../integration/docs/reference/lumio-bound-releases.md#supported-and-refused-operations);
unsupported calls refuse without planning, SQL or a legacy fallback.
`list-datasets` reads the approved live catalog; it is not source-free.

## Query and discovery

| Command | Purpose |
| --- | --- |
| `ariadne search TEXT --project DIR` | Read-only grouped discovery over admitted metrics, context, terms, and Examples. |
| `ariadne list-metrics --project DIR` | List governed metrics and dimensions. |
| `ariadne get-metric NAME --project DIR` | Execute a governed metric; supports repeatable `--dimension` and optional `--start` / `--end`. |
| `ariadne list-datasets --project DIR` | List queryable datasets from the approved source identity. |
| `ariadne search-context TEXT --project DIR` | Search the admitted context snapshot. |
| `ariadne resolve-term TERM --project DIR` | Resolve an admitted term or field request; guidance does not authorize joins. |
| `ariadne query-metrics --file REQUEST.json --project DIR` | Query the admitted multi-fact graph. |
| `ariadne query-detail --file REQUEST.json --project DIR` | Project fields through safe lookups from one root dataset. |
| `ariadne query-records --file REQUEST.json --project DIR` | Select bounded records from one known table; no aggregation and `governed: false`. |
| `ariadne define-metric --file REQUEST.json --project DIR` | Run an ephemeral ad-hoc metric; result is `governed: false` and `persistence: {status: not_saved}`. |
| `ariadne search-examples TEXT --project DIR` | Find admitted Example method references; `--include-history` and `--include-sql` opt into labeled history and SQL provenance. |
| `ariadne save-example --file REQUEST.json --project DIR` | Save an explicitly confirmed Example to a Git proposal; no separate review store. |

The local CLI emits one JSON result per successful operation and one JSON error object on failure. Request commands accept `--file` or standard input; consult `ariadne COMMAND --help` for exact request shapes. Ad-hoc results are not retained automatically. To keep a definition or Example, use revision-checked proposal edits/saves, validate and review the candidate, then stop for human admission.

## Git Authoring and human-only decisions

`ariadne-authoring` supports proposal start/read/edit, source proposal, inputs, schema refresh, validation, review, context resolution, and bounded mapping inspection. Every mutation targets an explicit proposal and current revision.

The following decisions remain local and human-only; they are not MCP tools:

- `ariadne-authoring approve-sources --project DIR --proposal ID --revision REV --source-digest DIGEST` grants permission for the exact resolved source identity.
- `ariadne-admit --project DIR --proposal ID --revision REV --reviewed-digest DIGEST --confirm` admits the exact reviewed and validated revision (optional mapping confirmations must be explicitly selected).
- `ariadne-authoring reconcile` records a permitted clean local rebase/merge after the admitted baseline advances; it never merges or resets automatically.

A Git commit, validation result, proposed source, authored status field or successful query is not source approval or admission. See [Git-backed authoring](../how-to/git-authoring.md) and the [Git-only route reference](git-authoring-migration.md) for the complete sequence.

## Document onboarding and static validation

Document onboarding uses Lumio's native intake (spec0035/ADR-0029): operator-authorized documents ride the SDK's `extract_source`/`CandidateRequest` contract through the authoring harness, with applicable original retention and the selected verbatim/distilled intent. There is no separate `ariadne-ingest` command and no Core document store; the optional `ariadne-data[documents]` extra adds supported converters for the bounded Seed-Notes document parts only.

`ariadne-validate ARTIFACT_DIR` performs source-free compile checks on an explicit artifact directory. Its result is partial structural evidence only: it does not open sources, perform live validation, approve sources, or admit content. Live validation is revision-bound through `ariadne-authoring validate` after human source approval.

## Optional transports and packages

The local CLI needs no server or model key for the deterministic query path.
Install Core 0.8.0 on Python >=3.14. Choose optional packages for the task:

- `ariadne-data[mcp]==0.8.0` adds the pinned MCP 2.2.0 transport.
- `ariadne-data[documents]==0.8.0` adds the supported document converters;
  it does not approve an input or supply model credentials.
- `lumio-wiki>=0.7,<0.8` is the required Lumio SDK foundation every Core
  install brings (mandatory pairing, ADR-0029/spec0035).
  `lumio-lancedb==0.6.0` is optional retrieval, not a Core requirement.

The separately distributed Ariadne Agent/Tau stack was retired 2026-11-12
(host agents only, ADR-0027); host agents use the packaged skill and these
CLI/MCP surfaces. DuckDB source-format extensions
and storage credentials remain host prerequisites; package extras do not create
or approve them.

## MCP

MCP binds one locally selected project with `--project DIR`. Choose `combined`, `analyst` or `authoring` at startup:

```bash
python -m ariadne.serve --project DIR
python -m ariadne.serve --project DIR --toolset analyst
python -m ariadne.serve --project DIR --toolset authoring
ariadne-analyst-mcp --project DIR
ariadne-authoring-mcp --project DIR
```

No tool argument selects another project, worktree, source identity, source approval or admission. Stdio is the default; HTTP is opt-in. Installing an adapter does not change the human governance gates.
