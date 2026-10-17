# Ariadne

**Governed metrics for AI agents.** Ariadne gives agents a reviewed source of truth for business metrics: definitions are compiled and queried by Ariadne, while business policies and caveats travel with the answer.

Raw text-to-SQL asks an agent to guess tables, joins, filters, and definitions. Ariadne separates those responsibilities into two layers:

- **Semantic Layer (OSI):** reviewed metric definitions, compiled to SQL and executed read-only by Ariadne.
- **Context Layer (OKF):** business policies, source caveats, and terminology that explain how to interpret a result.

Ariadne is a Python package with embedded DuckDB. Use it locally through the CLI, connect an agent through optional MCP, or add the separately distributed Ariadne Agent. A human remains responsible for source approval and for admitting the exact reviewed Git revision. Ariadne is not a BI dashboard or a high-concurrency metrics API.

## Documentation

The documentation follows [Diátaxis](https://diataxis.fr/):

- **[Tutorial](docs/tutorials/getting-started.md):** create a project and reach a first governed query.
- **[How-to guides](docs/README.md#how-to-guides):** complete specific tasks such as Git-backed authoring, private Docker MCP setup, or reading multiple S3 storages.
- **[Reference](docs/README.md#reference):** look up CLI commands, data-source configuration, and migration mappings.
- **[Explanation](docs/explanations/how-ariadne-works.md):** understand Ariadne's layers, governance gates, and authority boundaries.

The [documentation index](docs/README.md) lists all guides and references for **Ariadne 0.3.0**.

**Development candidate:** [Data Contracts](docs/reference/data-contracts.md) describes
Core’s limited, pinned ODCS v3.2.0 consumer profile, separate Git bindings and
as-of evidence. Source-free `ariadne search` includes a contracts group;
`list-datasets` remains an approved live-catalog operation. This is not full
ODCS compliance, a live health guarantee, or shared cross-layer identity (#76).

## Source development

Work on Ariadne itself happens from the package checkout, not inside a data project:

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -e .
source .venv/bin/activate
# Optional MCP example (after creating and admitting a project; requires .[mcp]):
uv pip install --python .venv/bin/python -e '.[mcp]'
examples/retail-demo/mcp_client.py --project /path/to/admitted/retail-project
```

For a candidate-wheel check, run `uv build`, install `dist/ariadne_data-*.whl`
into a fresh virtual environment, and follow the [getting-started tutorial](docs/tutorials/getting-started.md)
with the installed console scripts rather than the editable install.
