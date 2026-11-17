# Ariadne

**Governed metrics for AI agents.** Ariadne gives agents a reviewed source of truth for business metrics: definitions are compiled and queried by Ariadne, while business policies and caveats travel with the answer.

Raw text-to-SQL asks an agent to guess tables, joins, filters, and definitions. Ariadne separates those responsibilities into two layers:

- **Semantic Layer (OSI):** reviewed metric definitions, compiled to SQL and executed read-only by Ariadne.
- **Context Layer (OKF):** business policies, source caveats, and terminology that explain how to interpret a result.

Ariadne is a Python package with embedded DuckDB. Use it locally through the CLI, or connect an external host agent through the optional MCP server and the Ariadne skill surfaces. A human remains responsible for source approval and for admitting the exact reviewed Git revision. Ariadne is not a BI dashboard or a high-concurrency metrics API.

## Start locally

Follow the [getting-started tutorial](../../docs/tutorials/getting-started.md)
for the current native project route, then the
[context guide](../../docs/how-to/context-knowledge.md). Local CLI use needs no
service, app or cloud; its Lumio Knowledge Base is required, not an optional
second catalog.

The [historical joint tutorial](../../../../integration/docs/tutorials/lumio-ariadne-local.md)
preserves the Core 0.6.0 / SDK 0.4.0 example with **150 EUR recognized revenue
and two completed orders**. Its older package/layout contract is not the
current setup route. This source tree requires the SDK 0.7 line for Core 0.8;
exact build pairing is separate from package version strings.

## Documentation

The documentation follows [Diátaxis](https://diataxis.fr/):

- **[Tutorial](../../docs/tutorials/getting-started.md):** create a project and reach a first governed query.
- **[How-to guides](../../docs/README.md#how-to-guides):** complete specific tasks such as Git-backed authoring, private Docker MCP setup, or reading multiple S3 storages.
- **[Reference](../../docs/README.md#reference):** look up CLI commands, data-source configuration, and migration mappings.
- **[Explanation](../../docs/explanations/how-ariadne-works.md):** understand Ariadne's layers, governance gates, and authority boundaries.

The [documentation index](../../docs/README.md) lists all guides and references for **Ariadne 0.8.0**.

**Data Contracts:** the [reference](../../docs/reference/data-contracts.md) describes
Core’s limited, pinned ODCS v3.2.0 consumer profile, separate Git bindings and
as-of evidence. Source-free `ariadne search` includes a contracts group;
`list-datasets` remains an approved live-catalog operation. This is not full
ODCS compliance or a live health guarantee. Integrated releases bind these local
contract identities
alongside their knowledge identity; the contract itself does not become a portable
cross-system identifier.

**Lumio foundation:** Lumio is an independent product developed alongside
Ariadne in this shared repository; `ariadne-data` requires its compatible
`lumio-wiki` SDK (the 0.7 line for Core 0.8), while `lumio-wiki` never
requires Ariadne.
[Lumio bound releases](../../../../integration/docs/reference/lumio-bound-releases.md)
describe the required native context binding: one shared Content Commit, an
operator-confirmed overall admission activating a local immutable Bound Release,
strict `metric`/`policy`/`reference` profiles at revision 1 with revision-scoped
explicit opt-ins — revision 2 for the `dataset`/`table`/`computation` technical
profiles and revision 3 for the integrated `query-detail`/`query-records`/
`define-metric` operations with complete input Context — full required Policy
context on governed
answers, and source-free navigation over the pinned published pages. An optional S3
Knowledge transport (`--context-destination s3://…` plus a declared
`--context-storage-profile`) ships with Core 0.7.0, and its private native admission
records stay local to the admitting host. Git is the
standard transport and sync never activates a release — `ariadne status`
reports the local Git HEAD separately from the admitted release (see
[the local Git how-to](../../../../integration/docs/how-to/lumio-git-local.md)); the Lumio SDK is a required
dependency of Core, and exact build pairing is
recorded per release rather than assumed from package versions.

## Source development

Work on Ariadne itself happens from the member checkout, not inside a data
project. Run these from `products/ariadne/packages/ariadne-data` inside the
repository clone — the repository root is a non-distributable uv workspace and
must never be editable-installed (`-e .` targets this member directory only):

```bash
cd products/ariadne/packages/ariadne-data
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -e .
source .venv/bin/activate
# Optional MCP example (after creating and admitting a project; requires .[mcp]):
uv pip install --python .venv/bin/python -e '.[mcp]'
../../examples/retail-demo/mcp_client.py --project /path/to/admitted/retail-project
```

The `examples/` tree stays in the Ariadne product area (the path above is
member-relative). For a candidate-wheel check, run `uv build` in this member
directory, install `dist/ariadne_data-*.whl`
into a fresh virtual environment, and follow the [getting-started tutorial](../../docs/tutorials/getting-started.md)
with the installed console scripts rather than the editable install.
