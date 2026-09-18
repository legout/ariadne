---
name: ariadne
description: Work in an ariadne data project — query governed metrics via MCP with caveats attached, author context/semantic layers through the staging-to-promotion gate, and draft ad-hoc metrics without ever bypassing the compile gate.
---

# Ariadne data projects

Ariadne serves governed metrics over MCP (`ariadne-serve`, five tools). Numbers come
from OSI models compiled to SQL by a deterministic gate; the rules that make them
right live in the OKF context layer. The context layer routes and guides; the
semantic layer calculates; no computation ever bypasses the compile gate.

## The loop

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
5. **query** — MCP tools: `list_metrics` → `get_metric` for governed questions;
   `search_context` for rules; `list_datasets` → `define_metric` for anything
   unmodeled (auto-staged as a promotion proposal).

## Agent rules

- **Staging never serves.** Served artifacts arrive only by human promotion. Write
  only under `staging/`; never edit `context_layer/`, `semantic_layer/`, or the
  bundle's `index.md`/`log.md` (the promotion gate owns them).
- **Grain before joins.** A `define_metric` source must be grain-preserving: every
  join runs many-to-one on a key that is unique on the joined side. Resolve
  one-to-many and many-to-many per [references/grain-rubric.md](references/grain-rubric.md)
  — pre-aggregate the many side inside `source`, or the definition is rejected
  before compile (nothing staged, nothing executed).
- **Every number ships its caveats.** Governed `get_metric` responses carry a
  `context` field: the served metric page plus the full bodies of every policy it
  cites. Restate those caveats with every number and say `governed: true`;
  ad-hoc answers are `governed: false` proposals — label them as such, never as
  canonical.
- **`search_context` before novel questions.** The rule you are about to rediscover
  is probably already a policy page. Search first; if the question stays unmodeled,
  route it through `define_metric` so the definition lands in staging as a proposal.

Reference: [references/grain-rubric.md](references/grain-rubric.md) — the five
ADR-0006 resolution patterns for multi-cardinality joins.
