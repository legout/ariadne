# Contributing to ariadne-lumio

One repository, two independent products. Development happens in a single
[uv](https://docs.astral.sh/uv/) workspace with one development lockfile
(`uv.lock`); the repository root is coordination only and distributes
nothing.

## Setup

Python ≥ 3.14 and [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/legout/ariadne.git   # approved to be renamed ariadne-lumio; the URL keeps working
cd ariadne
uv sync    # install ALL workspace members (including the optional lumio-lancedb
           # adapter) plus the shared dev group — the full native suite's setup
```

To develop Core and the SDK **without** the optional LanceDB adapter, sync
exactly those members (uv ≥ 0.13 accepts repeated `--package` selections;
`--package <name>` alone syncs a single member):

```bash
uv sync --package ariadne-data --package lumio-wiki
```

## Component commands

Three explicit verification profiles (spec 0031 §4): Lumio, Ariadne Core,
and shared/joint. Never merge the products' test trees into one import
namespace.

### Lumio (from `products/lumio`)

```bash
cd products/lumio
uv run pytest -q -n 4                                        # full suite: tests, package tests, eval
uv run pytest -q packages/lumio-wiki/tests/test_capture.py   # focused tests stay serial
uv run ruff check .                                          # Lumio rules (E,F,I,UP,B)
```

Fixed four workers — never `-n auto`.

### Ariadne Core (from its member directory)

The native routine/release selection — the same selection the Core release
workflow runs — excludes exactly the three prepared-S3 capability modules
and names the two non-default paired integration modules explicitly
alongside the default suite:

```bash
cd products/ariadne/packages/ariadne-data
uv run pytest -q \
  --ignore=tests/test_s3_lakehouse.py \
  --ignore=tests/test_s3_storage_access.py \
  --ignore=tests/test_s3_storage_profiles.py \
  ../../../../integration/tests/lumio_metric_mvp.py \
  ../../../../integration/tests/lumio_local_context.py tests
uv run ruff check .     # Core rules (E,F,W,I,UP)
```

### Shared / joint (from the repository root)

```bash
uv run pytest -q -n 4   # shared coverage: tests/ + the two paired integration modules
uv run ruff check .     # shared trees only; product areas lint under their own configs
```

This shared profile is workspace coordination plus the paired Core/SDK
scenarios — not either product's complete native suite.

The three excluded modules are the prepared-S3 qualification gate (spec
0025 §§6–7): they require Docker, a local SeaweedFS service and an
installable DuckDB httpfs build, and they **refuse — never skip —** without
that prepared environment. They are therefore excluded from routine runs
and qualified separately in their prepared environment; no other module is
skipped.

### Wheels

Each member builds alone, for example
`uv build --package lumio-wiki --wheel`. Workspace imports are **not**
evidence of standalone wheel correctness — the isolated wheel verifiers
remain the gates (see [products/lumio/docs/packaging.md](products/lumio/docs/packaging.md)).

## Scope notes

- `products/ariadne/packages/ariadne-agent/` is a separate development
  environment, intentionally not a workspace member; its Tau dependencies
  are external to this repository and are not qualified here.
- Lint rules are component-scoped: the root rules govern the shared trees,
  Lumio's product-wide rules live in `products/lumio/pyproject.toml`, the
  Core member keeps its own, and examples split accordingly
  (`products/ariadne/examples/.ruff.toml`,
  `products/lumio/examples/.ruff.toml`,
  `integration/examples/.ruff.toml`).
- Vocabularies stay separate:
  [products/ariadne/CONTEXT.md](products/ariadne/CONTEXT.md) (Ariadne) and
  [products/lumio/CONTEXT.md](products/lumio/CONTEXT.md); see
  [CONTEXT-MAP.md](CONTEXT-MAP.md). Lumio records keep their original IDs
  under [products/lumio/project/](products/lumio/project/).
- Coming from the `legout/lumio-wiki` repository? The
  [migration reference](docs/migration-reference.md) maps old paths to their
  new canonical locations.
