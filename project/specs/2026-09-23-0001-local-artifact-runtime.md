# Specification: Local-first artifact runtime

| | |
| :--- | :--- |
| **Status** | **Approved** |
| **Approved by** | Owner, pi session 2026-09-23 — complete-design approval after interface decision rounds |
| **Scope approved** | Transport-neutral runtime; full-parity local JSON CLI; promoted-artifact discovery; optional MCP packaging; local-first packaged/generated skills and init behavior; compatibility and acceptance contracts in this document |
| **Supersedes** | The MCP-first consumption behavior in `project/specs/mvp-vertical-slice.md` §§1, 3–5, 7–8. All unaffected MVP invariants remain in force. |
| **Decision** | [ADR-0012](../adr/0012-local-first-artifact-runtime.md) |
| **Contract** | planning-contract v1; installed skill provenance unknown |
| **Later bounded-query amendment** | Owner-approved design [0014, revision 1](2026-10-08-0014-bounded-record-queries-and-results.md), 2026-10-08: adds a separate ungoverned record operation and shared result/deadline limits; output-refused ad-hoc computation stages nothing. Fitting metric values, full required caveats, compiler guards, legacy/managed root rules and local-first/optional-MCP behavior remain binding. Documentation capture does not authorize implementation or publication. |
| **Later Context extension** | Owner-approved [specification 0010, revision 1](2026-10-02-0010-context-layer-schema-and-identifiers.md), 2026-10-02: adds shared terminology resolution and discovery over human-admitted context-only Git revisions before any metric exists. Metric operations still require models and never fall back to raw SQL; legacy explicit-root discovery, full metric/Policy caveats and local-first/optional-MCP behavior remain binding. |
| **Later core redesign** | Owner-approved [modular-core/Git authoring design, revision 1](2026-10-02-0009-modular-core-git-authoring.md), 2026-10-02: replaces single-runtime ownership with shared core modules and adds split MCP registrations plus Combined. Breaking interfaces are permitted with explicit migration; governed artifact discovery for the new Git route is pinned to admitted revisions. Local-first/optional-MCP use, numerical behavior, compile/grain checks, required context, staged ad-hoc proposals and human-only admission remain binding. |
| **Later scoped extension** | [Harness-led authoring, revision 2](2026-09-24-0005-harness-led-authoring.md) adds optional authoring tools and private HTTP MCP for a server-configured project. This document's five-tool and no-HTTP constraints still govern its original query-runtime scope. |
| **Packaging amendment** | Owner, pi conversation 2026-09-29: the root distribution will be renamed to `ariadne-core`; the Python `ariadne.*` imports, CLI names, optional MCP extra, DuckDB engine and runtime behavior stay unchanged. Pending implementation in the Agent plan; the original `ariadne[mcp]` spelling below describes the pre-rename installation. |

## 1. Purpose

A local Ariadne installation must be fully usable through promoted Context Layer and Semantic Layer artifacts without starting or configuring MCP. Agents use the packaged Ariadne skill to invoke a local command; MCP remains an optional transport over the same runtime.

“Runtime” means the transport-neutral component that loads promoted artifacts, compiles governed or ad-hoc metric definitions, executes compiler output against registered sources, attaches context, and stages successful ad-hoc proposals.

## 2. Scope

In scope:

- one transport-neutral runtime implementing the five existing operations;
- an `ariadne` executable with local JSON commands for all five operations;
- safe discovery of promoted artifact roots;
- MCP as an optional package extra and adapter;
- local-first packaged skill, generated operational guidance, initialization, README, and demo behavior;
- compatibility for existing Python and MCP consumers.

Non-goals:

- changing OSI or OKF artifact formats;
- changing compiler, grain, execution, governance, or promotion semantics;
- moving existing author/profile/validate/promote/ingest commands under the new umbrella executable;
- a daemon, socket, HTTP service, or new transport;
- a human-formatted table output mode;
- transactional staging of the two ad-hoc proposal files;
- removing MCP support.

## 3. Architecture

`ariadne.runtime.AriadneRuntime` owns the behavior currently implemented by the MCP-oriented facade:

- `list_metrics()`;
- `list_datasets()`;
- `search_context(query, limit=10)`;
- `get_metric(name, dimensions=None, range=None)`;
- `define_metric(definition)`.

It depends on promoted OKF/OSI artifacts, the source registry or legacy database shorthand, and the staging root. It has no MCP dependency.

Two thin adapters call the same runtime:

1. `ariadne` serializes local command input/output as JSON.
2. `ariadne-serve` registers the five methods as MCP tools.

`ariadne.serve.Facade` remains import-compatible as an alias of `AriadneRuntime`. The MCP adapter must not duplicate compilation, execution, context, grain, or proposal-staging logic.

## 4. Local command interface

The package installs an `ariadne` executable with flat subcommands:

```text
ariadne list-metrics
ariadne list-datasets
ariadne search-context QUERY [--limit N]
ariadne get-metric NAME [--dimension NAME ...] [--start VALUE] [--end VALUE]
ariadne define-metric [--file PATH]
```

Common options are:

```text
--served PATH
--staging PATH
--sources PATH
--db PATH
```

`--sources` and `--db` are mutually exclusive. Their resolution otherwise follows the existing source-registry rules. `--staging` defaults to `staging` under the working directory.

`define-metric` reads one JSON definition object from `--file PATH`, or from stdin when `--file` is absent. Flags are used for the simpler `get-metric` request: `--dimension` is repeatable and `--start`/`--end` form the optional range object.

Every successful invocation writes exactly one JSON value followed by a newline to stdout. It preserves the corresponding runtime result shape. Temporal values serialize as ISO-8601 strings; decimal values serialize as strings to avoid precision loss. No progress or diagnostic text may contaminate stdout.

Every failed invocation writes exactly one JSON object to stderr and exits nonzero:

```json
{"error":{"type":"ValueError","message":"..."}}
```

Compiler, binder, grain, and unknown-metric messages remain verbatim in `message`. A failed operation writes no success value to stdout.

## 5. Promoted-artifact discovery

An explicit `--served PATH` wins. The path is valid only when it contains both `context_layer/` and `semantic_layer/models/`.

Without `--served`, the CLI examines exactly two candidates in order:

1. the working directory;
2. `served/` under the working directory.

Exactly one valid candidate is selected. Zero valid candidates produce an actionable error naming both expected layouts. Two valid candidates produce an ambiguity error requiring `--served`; the CLI never guesses between two promoted roots.

Only the selected promoted Semantic Layer supplies governed metrics. Context search keeps its existing behavior of returning served pages plus explicitly draft-marked pages from the staging root.

## 6. Preserved invariants

Both adapters use the same runtime and therefore preserve:

- deterministic OSI-to-SQL compilation;
- the exactly-one-statement guard;
- EXPLAIN binding before execution;
- grain-preserving join enforcement;
- read-only source connections;
- governed metric context and cited-policy attachment;
- `governed: true` for promoted metrics and `governed: false` for ad-hoc metrics;
- collision-safe, never-overwriting ad-hoc proposal staging;
- human-only promotion.

There remains no path from local CLI arguments, stdin, or MCP tool arguments to execution that bypasses the compiler.

## 7. Packaging and initialization

`mcp>=1.2,<2` moves from base dependencies to the `mcp` optional extra. The base installation supports the full local interface without importing or installing MCP.

`ariadne-serve` remains installed. When its optional dependency is absent, it exits nonzero with an actionable instruction to install the root distribution's `mcp` extra (`ariadne[mcp]` before the rename, `ariadne-core[mcp]` afterward); local commands remain unaffected.

`ariadne-init` does not create `.mcp.json` by default. `ariadne-init --with-mcp` creates the registry-aware MCP configuration. Existing `.mcp.json` files are never deleted.

The existing `ariadne-author`, `ariadne-profiler`, `ariadne-validate`, `ariadne-promote`, `ariadne-ingest`, `ariadne-init`, `ariadne-skill`, and `ariadne-serve` entry points remain available.

## 8. Skill and generated-artifact behavior

The packaged Ariadne skill teaches the local CLI as the default workflow:

1. list promoted metrics;
2. search context before novel questions;
3. query a governed metric and report its attached caveats;
4. list datasets and define an ad-hoc metric when no governed metric fits;
5. label governed and ad-hoc answers accurately.

MCP appears only as an optional integration section.

The author-generated operational query guide becomes local-first and cites the `ariadne` executable. Newly authored bundles must not claim that MCP is required. Previously promoted pages are historical artifacts and are changed only through the normal author → staging → human-promotion flow.

The demo and README show local querying first. Optional MCP examples remain available when the extra is installed.

## 9. Failure behavior

- Invalid or ambiguous promoted roots fail before a source connection is opened.
- Invalid JSON input fails before compilation, execution, or staging.
- Runtime compiler, binder, grain, and unknown-metric failures preserve their current messages and side-effect guarantees.
- A missing MCP extra affects only `ariadne-serve` and MCP-specific initialization.
- Successful ad-hoc staging retains the current two-write behavior; transactional staging is explicitly outside this revision.

## 10. Acceptance criteria

1. In an environment where `mcp` is not installed, importing `ariadne.runtime` and running all five `ariadne` operations succeeds.
2. `ariadne list-metrics` and `ariadne list-datasets` return the same JSON data as the corresponding runtime methods.
3. A governed `ariadne get-metric` golden query returns rows, compiled SQL, `governed: true`, the full metric page, and cited policy bodies.
4. `ariadne search-context` returns served hits and draft-marked staged hits with the existing ranking and limit behavior.
5. A successful stdin- or file-driven `ariadne define-metric` returns `governed: false` and stages one OSI proposal plus one OKF draft without overwriting collisions.
6. An invalid definition executes nothing and stages nothing; the CLI emits one JSON error on stderr and exits nonzero.
7. Root discovery succeeds independently for root and `./served` layouts, and fails deterministically for missing and ambiguous layouts.
8. CLI stdout parses as exactly one JSON value for results containing dates and decimals.
9. The existing MCP acceptance suite passes with the root distribution's `mcp` extra installed (`ariadne[mcp]` before the rename, `ariadne-core[mcp]` afterward) and observes the same result envelopes as the local CLI.
10. Without the extra, `ariadne-serve` prints the optional-extra installation hint and exits nonzero.
11. `ariadne-init` omits `.mcp.json` by default and creates it only with `--with-mcp`, without removing an existing file.
12. A fresh agent using only the installed skill and base package answers one governed and one unmodeled question, includes required caveats/governance labels, and starts no MCP server.

## 11. Capture checkpoint

- **Vocabulary:** “runtime” is defined in §1. No project glossary change is required.
- **Decisions:** the durable local-first/optional-MCP choice is recorded in ADR-0012.
- **Behavior:** scope, non-goals, interfaces, failures, compatibility, and observable acceptance are owned by this approved specification.
- **Uncertainty:** no unresolved material design decision remains. Implementation requires a separate approved implementation plan and execution authority.
