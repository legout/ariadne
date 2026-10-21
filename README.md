# ariadne-lumio

One repository, two independent products: **Ariadne Core** (`ariadne-data`)
for governed metrics, and the **Lumio Knowledge Base foundation**
(`lumio-wiki`, plus the optional `lumio-lancedb` adapter). Colocation serves
shared development and review only — no product requires the other, and
installing both never activates their integration.

> **Repository naming:** the canonical location is approved to be renamed
> from `legout/ariadne` to `legout/ariadne-lumio` at an explicitly authorized
> cutover that has **not happened yet**; until then this repository is served
> from `legout/ariadne`. See the
> [migration reference](docs/migration-reference.md).

## Choose your entry

### 1. Lumio alone — a portable Knowledge Base

Build, review, search and publish a portable Knowledge Base for your coding
agents. No Ariadne installation, data source, model or service is required
for the local flow; `lumio-lancedb` stays an optional retrieval adapter.

```bash
pip install lumio-wiki   # load, validate, search, traverse, ingest, publish
```

Runnable local example: the
[quickstart](products/lumio/docs/quickstart.md), scripted end-to-end by
[`products/lumio/examples/onboarding-journey/`](products/lumio/examples/onboarding-journey/);
capture adapters and a real-world Knowledge Base live under
[`products/lumio/examples/`](products/lumio/examples/). Package details:
[`products/lumio/packages/lumio-wiki/README.md`](products/lumio/packages/lumio-wiki/README.md).

### 2. Ariadne alone — governed metrics

Define and calculate governed metrics over approved data with an explicit
human review gate. Standalone mode works without Lumio.

```bash
pip install ariadne-data   # local CLI + query engine; optional extras: [mcp], [documents]
```

Runnable local example: the
[getting-started tutorial](products/ariadne/docs/tutorials/getting-started.md),
plus standalone source fixtures in
[`products/ariadne/examples/retail-demo/`](products/ariadne/examples/retail-demo/)
(an already-admitted project; not the combined onboarding recipe). Package
details:
[`products/ariadne/packages/ariadne-data/README.md`](products/ariadne/packages/ariadne-data/README.md).

### 3. Lumio + Ariadne together — curated context with governed calculations

Use curated Knowledge Base context with governed calculations. Integration is
explicit: an installed compatible SDK, compatible artifacts, source approval
and an operator-confirmed overall admission are required — colocation or
installing both packages activates nothing.

Minimum installation for this route is both published packages
(`pip install ariadne-data lumio-wiki`); the joint tutorial pins the exact
compatible pair it exercises (`ariadne-data==0.6.0`, `lumio-wiki==0.4.0`).

Runnable local example: the joint tutorial
[Lumio + Ariadne locally](integration/docs/tutorials/lumio-ariadne-local.md),
with its complete synthetic project in
[`integration/examples/local-lumio-ariadne/`](integration/examples/local-lumio-ariadne/) — three
synthetic orders, **150 EUR recognized revenue and two completed orders**
with the complete governing Policy and citations, then a Git update that
stays inactive until reviewed confirmation.

## Using versus developing

- **Using the products:** install the published wheels into your own
  environment (`pip install lumio-wiki` / `pip install ariadne-data`); all
  packages require Python ≥ 3.14. You do not need this checkout, and
  standalone use never requires the other product — only the explicit
  integrated route (entry 3) installs both.
- **Developing this repository:** one uv workspace with a single development
  lockfile; the root distributes nothing. Component commands and scope notes:
  [CONTRIBUTING.md](CONTRIBUTING.md).

## Licensing

Licensing is component-specific. The Lumio members are Apache-2.0 (each
member directory carries its license file); `ariadne-data` currently declares
no project license. Vendored notices (for example the ODCS schema license)
stay attached to their artifacts. No repository-wide license is implied by
colocation.

The private Lumio web application is a separate product, clearly distinct
from this public foundation; the separately distributed Ariadne Agent is not
part of the workspace either. Neither is required by any entry above.
