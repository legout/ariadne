---
name: ariadne
description: Work in an ariadne data project — query governed metrics with the local ariadne CLI (caveats attached), author context/semantic layers through the staging-to-promotion gate, and draft ad-hoc metrics without ever bypassing the compile gate.
---

# Ariadne data projects

Ariadne serves governed metrics through the local `ariadne` command — no
server, no setup beyond the base package. Numbers come from OSI models compiled
to SQL by a deterministic gate; the rules that make them right live in the OKF
context layer. The context layer routes and guides; the semantic layer
calculates; no computation ever bypasses the compile gate.

## Querying — the default workflow

Common options follow the subcommand: `--sources ariadne.yaml` (or `--db
PATH`), and `--served PATH` when the promoted root is not discoverable. Run
from the project root: the CLI finds promoted artifacts in the working
directory or under `./served`; if both match (ambiguous) or neither does, it
fails with an actionable error — pass `--served PATH` to select the root
explicitly. Never start a server just to answer a question.

1. **List governed metrics** — `ariadne list-metrics --sources ariadne.yaml`.
   Start every question here: if a governed metric answers it, query it
   governed.
2. **Search context before novel questions** — `ariadne search-context
   "cancelled orders" --sources ariadne.yaml`. The rule you are about to
   rediscover is probably already a policy page; restate its caveats with any
   number it affects.
3. **Query a governed metric** — `ariadne get-metric gross_margin --dimension
   region --start 2024-01-01 --sources ariadne.yaml`. The result carries
   `governed: true`, the compiled SQL, and a `context` block: the served
   metric page plus the full body of every policy it cites.
4. **Unmodeled question?** `ariadne list-datasets --sources ariadne.yaml`,
   then `ariadne define-metric --file def.json --sources ariadne.yaml` (or
   pipe the JSON definition via stdin when `--file` is absent). The definition
   runs read-only through the same compile gate, returns `governed: false`,
   and stages an OSI proposal plus an OKF draft under `staging/` for human
   promotion.
5. **Label answers accurately.** Governed numbers ship with their caveats and
   `governed: true`; ad-hoc numbers are `governed: false` proposals — label
   them as such, never as canonical.

## The authoring loop

1. **profile** — `ariadne-profiler` summarizes every source declared in
   `ariadne.yaml` (schemas, keys, cardinalities) so models fit the real data.
2. **author** — `ariadne-author --sources ariadne.yaml --notes data/seed_notes.md`
   drafts the OKF bundle + OSI models into `staging/` (validation loop included;
   unresolvable failures stage as `status: review_needed`).
3. **review staging** — a human reads `staging/`. The authoring agent never writes
   anywhere else.
4. **human promote** — `ariadne-promote` merges staged into the served
   `context_layer/` + `semantic_layer/`, stamps `verified`, regenerates indexes.
   Agents never promote.
5. **query** — the local CLI loop above: `list-metrics` → `get-metric` for
   governed questions; `search-context` for rules; `list-datasets` →
   `define-metric` for anything unmodeled (auto-staged as a promotion
   proposal).

## Agent rules

- **Staging never serves.** Served artifacts arrive only by human promotion. Write
  only under `staging/`; never edit `context_layer/`, `semantic_layer/`, or the
  bundle's `index.md`/`log.md` (the promotion gate owns them).
- **Grain before joins.** A `define_metric` source must be grain-preserving: every
  join runs many-to-one on a key that is unique on the joined side. Resolve
  one-to-many and many-to-many per [references/grain-rubric.md](references/grain-rubric.md)
  — pre-aggregate the many side inside `source`, or the definition is rejected
  before compile (nothing staged, nothing executed).
- **Every number ships its caveats; governed answers cite provenance.** Governed
  `get_metric` responses carry a `context` field: the served metric page plus
  the full bodies of every policy it cites. Restate those caveats with every
  number, say `governed: true`, and cite the context actually returned: the
  served metric page and the relevant Policy paths exactly as the page's
  `sources` list gives them (e.g. `context_layer/metrics/gross_margin.md` and
  `policies/emea-currency-cutover.md`) — never invented, remembered, or guessed
  paths. Ad-hoc answers are `governed: false` proposals — label them as such,
  never as canonical.
- **`search_context` before novel questions.** The rule you are about to rediscover
  is probably already a policy page. Search first; if the question stays unmodeled,
  route it through `define_metric` so the definition lands in staging as a proposal.

## Optional: MCP integration

MCP registers the same five operations as tools over a server — useful for
remote or host-integrated tool registration. It is optional; the local CLI
above is the default workflow and works without any of this. Install
`ariadne[mcp]` into the same Python environment that provides the `ariadne`
CLI. For this source checkout, run the install from the Ariadne package
checkout (the directory containing `pyproject.toml`), not from the data project
root:

```bash
uv pip install --python .venv/bin/python -e '.[mcp]'
```

Then from the data project's root, opt in to its MCP config and start the
server:

```bash
ariadne-init --with-mcp .
ariadne-serve --sources ariadne.yaml
```

Reference: [references/grain-rubric.md](references/grain-rubric.md) — the five
ADR-0006 resolution patterns for multi-cardinality joins.
