# Retail source fixtures and optional MCP client

For a complete runnable local onboarding project, start with
[Local Lumio + Ariadne](../../docs/tutorials/lumio-ariadne-local.md).

This directory holds source-generation utilities, Seed Notes and a registry
sample for SQLite shop data plus Parquet support tickets. The data differs from
the new three-order tutorial. Generation does not approve a source or supply a
reviewed semantic catalog; do not copy the registry into a live project and
assume it has been admitted. Read the Seed Notes and author/review the desired
business definitions through the normal proposal workflow.

`mcp_client.py --project /absolute/path/to/admitted/project` demonstrates the
optional Core MCP adapter and requires `ariadne-data[mcp]` in its environment.
Its selected data project must already have the operator's valid admission.
It does not install or certify the separately versioned Ariadne Agent/Tau stack.
