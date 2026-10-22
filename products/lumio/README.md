# Lumio Knowledge Base foundation

Build a portable Knowledge Base from Markdown pages, search it with citations,
and publish an explicitly reviewed Git revision. The public Lumio foundation
works on its own: local use needs no Ariadne installation, model provider,
database service or cloud account.

## Choose a package

| Package | Purpose |
| --- | --- |
| [`lumio-wiki`](packages/lumio-wiki/README.md) · [PyPI](https://pypi.org/project/lumio-wiki/) | Canonical page format, validation, model-free search, graph traversal, ingestion, Git authoring, reviewed publication, CLI and packaged Agent Skill. |
| [`lumio-lancedb`](packages/lumio-lancedb/README.md) · [PyPI](https://pypi.org/project/lumio-lancedb/) | Optional LanceDB adapter for indexed BM25, semantic and hybrid retrieval over the same Knowledge Base and citation contracts. |

Both packages require **Python 3.14 or newer** and are licensed Apache-2.0.
The base SDK stays lightweight; the adapter depends on the SDK, never the
other way around. The private Lumio web application is separate and is not
required to use either package.

## Start locally

```bash
pip install lumio-wiki
lumio-wiki doctor
lumio-wiki init ./my-knowledge
lumio-wiki validate ./my-knowledge
```

Continue with the [local/Git quickstart](docs/quickstart.md): author a page,
review an exact commit, explicitly admit its publication, then search the
published Knowledge Base with grounded citations. The
[onboarding example](examples/onboarding-journey/) contains the runnable
journey. Validation and ordinary reads need no Git repository; authoring and
publication admission use Git. Validation never grants publication authority.

Optional capabilities install separately:

```bash
pip install 'lumio-wiki[documents]'  # PDF, image, Office and HTML converters
pip install 'lumio-wiki[llm]'        # OpenAI-compatible unattended distillation
pip install 'lumio-wiki[s3]'         # S3-compatible storage
pip install 'lumio-wiki[mcp]'        # Read-only MCP server
pip install lumio-lancedb           # Indexed retrieval adapter
```

Installing an adapter does not build an index or change publication permissions.
See the [package guide](packages/lumio-wiki/README.md) for API and CLI details.

## Lumio and Ariadne together

Lumio supplies curated knowledge; [Ariadne](../ariadne/packages/ariadne-data/README.md)
supplies governed calculations over approved analytical sources. They are
independent products. Using both is optional and requires compatible builds,
explicit configuration and a new matching human admission; installation alone
activates nothing.

The [joint local tutorial](../../integration/docs/tutorials/lumio-ariadne-local.md)
shows the complete flow with synthetic orders and Policy citations. Its
historical baseline and the newer query extension are labeled separately.
See [current pairing and boundaries](docs/ariadne-context.md) for the
Core 0.7.0 pairing with the Lumio 0.5 family and optional pinned S3
consumption.

## Documentation and examples

- [Usage and CLI](docs/usage.md)
- [Compiled Page format](docs/kb-format.md)
- [Optional S3 publication](docs/howto-s3-publish.md)
- [Capture adapters](examples/capture-adapters/)
- [Packaging and optional dependencies](docs/packaging.md)
- [Changelog](CHANGELOG.md), [0.5.1 patch notes](docs/release-notes/v0.5.1.md)
  and the [0.5.0 feature baseline](docs/release-notes/v0.5.0.md)
- [Development instructions](../../CONTRIBUTING.md)
- [Report an issue](https://github.com/legout/ariadne/issues)
