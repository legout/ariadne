# lumio-lancedb

Optional **LanceDB retrieval adapter** for the
[Lumio Knowledge Base foundation](https://github.com/legout/ariadne/tree/main/products/lumio).
It adds indexed BM25, vector/semantic and hybrid retrieval to `lumio-wiki`,
preserving its evidence, citation and retrieval-result contracts.

## Install

Requires **Python 3.14 or newer**.

```bash
pip install lumio-lancedb
```

The adapter depends on `lumio-wiki`, LanceDB, PyArrow and `msgspec[yaml]`.
The 0.5.0 adapter requires `lumio-wiki>=0.5.0,<0.6.0`.
Installing the adapter alone does not build an index; select and configure
it explicitly through the supported SDK or CLI composition.

Optional capabilities:

```bash
pip install 'lumio-lancedb[embeddings]'  # Local sentence-transformers / Torch
pip install 'lumio-lancedb[s3]'          # Remote S3-compatible index support
```

Torch is excluded from the base adapter. Semantic retrieval additionally
requires a configured embedding implementation and a built semantic index;
BM25 retrieval does not require a model. The index is derived data: canonical
Markdown pages remain the Knowledge Base's source of truth.

## Start with the Knowledge Base

Use the [local/Git quickstart](https://github.com/legout/ariadne/blob/main/products/lumio/docs/quickstart.md)
to create and publish a Knowledge Base, then follow the
[retrieval and CLI guide](https://github.com/legout/ariadne/blob/main/products/lumio/docs/usage.md)
to add indexed retrieval. The
[SDK package guide](https://github.com/legout/ariadne/blob/main/products/lumio/packages/lumio-wiki/README.md)
describes the shared API, citations and explicit publication admission.

`lumio-wiki` works independently of this adapter and never imports it.
Ariadne is also optional; see the
[joint tutorial](https://github.com/legout/ariadne/blob/main/integration/docs/tutorials/lumio-ariadne-local.md)
for separately admitted knowledge and governed calculations.

## Project links

- [Repository](https://github.com/legout/ariadne)
- [Packaging and compatibility](https://github.com/legout/ariadne/blob/main/products/lumio/docs/packaging.md)
- [Changelog](https://github.com/legout/ariadne/blob/main/products/lumio/CHANGELOG.md)
- [Issues](https://github.com/legout/ariadne/issues)
- [Apache-2.0 license](https://github.com/legout/ariadne/blob/main/products/lumio/packages/lumio-lancedb/LICENSE)
