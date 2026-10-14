# How Ariadne works

Ariadne separates **how a metric is calculated** from **what the result means**. The Semantic Layer owns executable metric definitions; the Context Layer supplies business meaning, policies, source descriptions, and caveats. Ariadne brings both into the query path without letting context notes turn into executable authority.

## Two layers, different jobs

### Semantic Layer

Metrics are declared in OSI YAML. Ariadne validates and compiles the declarations to SQL, checks query safety and grain-preserving relationships, and executes read-only. Governed queries do not ask the agent to invent SQL for a business metric.

### Context Layer

Context pages describe policies, tables, schemas, business terms, and other guidance. Ariadne can return the relevant pages and policies with a result so the agent can explain caveats. A term alias, observed value, schema measurement, example answer, or routing-map pointer is guidance—not permission to join tables, rewrite a query, or override a required policy.

## The governed path

```text
operator declares sources
        ↓
human approves the resolved source identity
        ↓
agent or operator drafts typed artifacts in a proposal
        ↓
validation + review of the exact candidate revision
        ↓
human admits that reviewed revision (or promotes a legacy bundle)
        ↓
Ariadne serves the admitted catalog and approved sources
        ↓
compiled, read-only query → result + applicable context/policies
```

Each gate has a distinct meaning:

- **Source approval** authorizes a resolved source identity for the workflow. A filename detected by setup is only a hint and is not approval.
- **Validation** checks declared artifacts; it does not admit them.
- **Review** describes a candidate; reading the report is not sign-off.
- **Git Review Admission** binds a human decision to the exact reviewed and validated revision. A Git commit by itself is not admission.
- **Legacy Promotion** is the separate human gate for staged projects.

The Git-managed and legacy routes remain distinct. A managed query reads the pinned admitted snapshot; it never falls back to a mutable project tree or proposal. A legacy query reads the human-promoted served artifacts. Ariadne does not silently migrate one route into the other.

## Source access is not metric governance

Source approval concerns which resolved source identity may be opened by the authoring workflow. It does not admit metric definitions or context pages. Conversely, a read-only data connection does not make a query governed: governance comes from a human-admitted Semantic Layer definition or a human-promoted legacy catalog.

Native DuckDB catalogs are trusted inputs, not sandboxes. Read-only attachment protects a catalog from writes, but does not isolate filesystem or network access, freeze remote backing data, or make a view safe to execute. The operator must trust the catalog and its backing resources. See the [data source reference](../reference/data-sources.md#remote-and-native-duckdb-paths) for the connection details.

## What the result means

A governed result identifies its governance status and carries its relevant metric/context information, including applicable Policy caveats. `governed: true` means the result came through a human-governed catalog route. It does **not** by itself prove that the numeric value was independently attested against an external oracle.

An ad-hoc metric is explicitly `governed: false`. It can be useful for exploration, but it does not become a governed definition without the normal proposal, validation, review, and human gate. Saved Answer Examples are labeled method references, not cached query results: a new question is answered with a fresh query.

## Integrations do not change authority

The local CLI is the core interface. MCP and the separately installed Ariadne Agent are adapters over the same Ariadne operations; they do not gain source-approval, admission, Promotion, or example-review authority. In authoring, agents can draft and inspect proposals, while the operator performs the human-only decisions.

For task-oriented steps, see the [getting-started tutorial](../tutorials/getting-started.md), [Git-backed authoring](../how-to/git-authoring.md), and [Context knowledge](../how-to/context-knowledge.md).
