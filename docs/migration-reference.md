# Migration reference: lumio-wiki → this repository

The public Lumio foundation moved from its own repository (`legout/lumio-wiki`)
into this one, preserving the complete public commit history. In the current
isolated migration candidate both histories are reachable from the migration
branch; default-branch reachability follows only from the separately
authorized integration. Authority: Ariadne
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
- Configuring release credentials in this repository (see below).

None of these are live yet. Historical citations of the old URLs remain
valid as history and are not rewritten automatically.

## Release-credential prerequisites (owner actions, honestly scoped)

Migration copies no credentials and creates no settings; token values and
scopes were never read or inferred, only secret/environment **names** were
inventoried:

- The target repository (`legout/ariadne`) currently has **no GitHub
  environments**. The old SDK repository has `pypi` and `testpypi`
  environments.
- `PYPI_API_TOKEN` secret names exist in both repositories. Core publishing
  keeps its current model — a repository secret, no environment. The Lumio
  family channel keeps its native model — the `pypi` environment plus
  `PYPI_API_TOKEN`. Any credential-model change is an owner decision, not a
  migration side effect.
- Whether a `lumio-v*` release can publish is not guaranteed either way by
  configuration alone: GitHub Actions makes repository secrets available to
  jobs, with same-named environment secrets taking precedence when
  configured, and this repository already carries a `PYPI_API_TOKEN`
  repository-secret name whose package scope is unknown (never read or
  inferred). M5 readiness therefore requires owner verification of the
  `pypi` environment and the token's scope **before any release** — the
  missing environment is an owner prerequisite to verify, not a fail-closed
  runtime guard.
- Neither native release workflow creates GitHub Releases; none was added
  here. External configuration gaps are disclosed rather than papered over.
