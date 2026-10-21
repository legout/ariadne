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

Run from the repository root unless noted. The two products' test trees are
deliberately separate default selections; never merge them into one import
namespace.

### Lumio foundation (the root's default selection)

```bash
uv run pytest -q -n 4                                        # full suite: tests/lumio, package tests, eval/lumio
uv run pytest -q packages/lumio-wiki/tests/test_capture.py   # focused tests stay serial
uv run ruff check .                                          # Lumio-side root rules (E,F,I,UP,B)
```

Fixed four workers — never `-n auto`.

### Ariadne Core (from its member directory)

The native routine/release selection — the same selection the Core release
workflow runs, relative to the member — excludes exactly the three
prepared-S3 capability modules and names the two non-default Lumio-paired
modules explicitly alongside the default suite:

```bash
cd packages/ariadne-data
uv run pytest -q \
  --ignore=tests/test_s3_lakehouse.py \
  --ignore=tests/test_s3_storage_access.py \
  --ignore=tests/test_s3_storage_profiles.py \
  tests/lumio_metric_mvp.py tests/lumio_local_context.py tests
uv run ruff check .     # Core rules (E,F,W,I,UP)
```

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
remain the gates (see [docs/lumio/packaging.md](docs/lumio/packaging.md)).

## Scope notes

- `ariadne-agent/` is a separate development environment, intentionally not a
  workspace member; its Tau dependencies are external to this repository and
  are not qualified here.
- Lint rules are component-scoped: the root rules govern Lumio-side files,
  `packages/ariadne-data` keeps its own, and `examples/` splits accordingly
  (`examples/.ruff.toml`, `examples/lumio/.ruff.toml`).
- Vocabularies stay separate: [CONTEXT.md](CONTEXT.md) (Ariadne) and
  [project/lumio/CONTEXT.md](project/lumio/CONTEXT.md); see
  [CONTEXT-MAP.md](CONTEXT-MAP.md). Lumio records keep their original IDs
  under [project/lumio/](project/lumio/).
- Coming from the `legout/lumio-wiki` repository? The
  [migration reference](docs/migration-reference.md) maps old paths to their
  new canonical locations.
