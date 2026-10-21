# Migration reference: lumio-wiki → this repository

The public Lumio foundation moved from its own repository (`legout/lumio-wiki`)
into this one, preserving the complete public commit history — both source
histories are reachable from the default branch. Authority: Ariadne
[ADR-0027](../project/adr/0027-public-monorepo.md) and
[spec 0030](../project/specs/2026-10-21-0030-public-monorepo.md); the scoped
location amendment to the Lumio decision is in
[ADR-0025](../project/lumio/adr/0025-repository-split.md).

## Path map

| Old (`legout/lumio-wiki`) | New (here) |
| --- | --- |
| `packages/lumio-wiki/` | `packages/lumio-wiki/` (unchanged) |
| `packages/lumio-lancedb/` | `packages/lumio-lancedb/` (unchanged) |
| `tests/` | `tests/lumio/` |
| `eval/` | `eval/lumio/` |
| `scripts/` | `scripts/lumio/` |
| `experiments/` | `experiments/lumio/` |
| `docs/` | `docs/lumio/` |
| `docs/release-notes/` | `docs/lumio/release-notes/` |
| `CHANGELOG.md` | `docs/lumio/CHANGELOG.md` |
| `examples/` | `examples/lumio/` |
| `project/` (adr, specs, plans, research, agents) | `project/lumio/…` (original IDs preserved) |
| `CONTEXT.md` | `project/lumio/CONTEXT.md` |
| `README.md` | `packages/lumio-wiki/README.md` |
| `LICENSE` | `packages/lumio-wiki/LICENSE` and `packages/lumio-lancedb/LICENSE` |
| `pyproject.toml` / `uv.lock` (old workspace root) | root `pyproject.toml` / `uv.lock` (the workspace now also includes `packages/ariadne-data`) |
| `.github/workflows/ci.yml`, `lumio-lancedb-wheel.yml` | unchanged paths (commands follow the relocated code) |

## Pending external steps (not yet performed)

- Renaming this repository to `legout/ariadne-lumio`; the current URL will
  redirect, so existing links keep working.
- A cutover notice on the old `legout/lumio-wiki` repository and stopping its
  duplicate development/release workflows.
- The release-channel configuration in this repository (`core-v*` /
  `lumio-v*` tags).

None of these are live yet. Historical citations of the old URLs remain
valid as history and are not rewritten automatically.
