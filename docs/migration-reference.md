# Migration reference: lumio-wiki → this repository

The public Lumio foundation moved from its own repository (`legout/lumio-wiki`)
into this one, preserving the complete public commit history. In the current
isolated migration candidate both histories are reachable from the migration
branch; default-branch reachability follows only from the separately
authorized integration. Authority: Ariadne
[ADR-0027](../project/adr/0027-public-monorepo.md) and
[spec 0030](../project/specs/2026-10-21-0030-public-monorepo.md); the scoped
location amendment to the Lumio decision is in
[ADR-0025](../products/lumio/project/adr/0025-repository-split.md).

A second layout transition — the product-area layout of
[spec 0031](../project/specs/2026-10-21-0031-product-oriented-layout.md) —
relocated the paths below again; see
[the product-area path map](#product-area-layout-spec-0031) for the current
canonical locations. The first map stays as the historical record of the
`legout/lumio-wiki` consolidation.

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

## Product-area layout (spec 0031)

The product-area migration (spec 0031 revision 1, ADR-0027 amendment) gave
both products equal, explicit ownership in the source tree and moved the
joint user journey to a dedicated integration area. GitHub file moves are
**not** HTTP redirects: floating `main` URLs of the old paths stop resolving;
repository-owned links were repaired to the new canonical locations below,
and immutable commit-qualified citations keep their historical meaning. The
workspace root, lockfile and release channels are unchanged in identity; only
member locations moved.

| Spec-0030-era path | Spec-0031 path |
| --- | --- |
| `packages/ariadne-data/` | `products/ariadne/packages/ariadne-data/` |
| `ariadne-agent/` | `products/ariadne/packages/ariadne-agent/` (still a separate environment, not a workspace member) |
| `packages/lumio-wiki/` | `products/lumio/packages/lumio-wiki/` |
| `packages/lumio-lancedb/` | `products/lumio/packages/lumio-lancedb/` |
| `CONTEXT.md` | `products/ariadne/CONTEXT.md` (scope corrected to Ariadne ownership) |
| `project/lumio/CONTEXT.md` | `products/lumio/CONTEXT.md` |
| `CHANGELOG.md` | `products/ariadne/CHANGELOG.md` |
| `docs/lumio/CHANGELOG.md` | `products/lumio/CHANGELOG.md` |
| `docs/` (Ariadne-only entries) | `products/ariadne/docs/` (same categories) |
| `docs/lumio/` | `products/lumio/docs/` (incl. release notes) |
| `docs/tutorials/lumio-ariadne-local.md` | `integration/docs/tutorials/lumio-ariadne-local.md` |
| `docs/how-to/lumio-git-local.md` | `integration/docs/how-to/lumio-git-local.md` |
| `docs/reference/lumio-bound-releases.md` | `integration/docs/reference/lumio-bound-releases.md` |
| `docs/migration-reference.md` | unchanged (shared) |
| `examples/retail-demo/` | `products/ariadne/examples/retail-demo/` |
| `examples/lumio/` | `products/lumio/examples/` |
| `examples/local-lumio-ariadne/` | `integration/examples/local-lumio-ariadne/` |
| `tests/lumio/` | `products/lumio/tests/` (exceptions below) |
| `tests/lumio/test_workspace_layout.py`, `test_workspace_certification.py` | `tests/` (shared workspace/packaging checks) |
| `packages/ariadne-data/tests/lumio_metric_mvp.py`, `lumio_local_context.py` (+ `fixtures/lumio_context_baseline/`) | `integration/tests/` |
| `eval/lumio/` | `products/lumio/eval/` |
| `scripts/lumio/` | `products/lumio/scripts/` |
| `experiments/lumio/` | `products/lumio/experiments/` |
| Root `Dockerfile`, `compose.yaml`, `compose.loopback.yaml`, `.env.example` | `products/ariadne/deploy/` (build context stays the repository root) |
| `.pi-lens-probe-home/` | `project/research/pi-lens-probe/` (shared tooling evidence) |
| `project/adr/`, `specs/`, `plans/`, `research/` (Ariadne-owned) | `products/ariadne/project/…` (original IDs preserved) |
| `project/lumio/` records | `products/lumio/project/…` (original IDs preserved) |
| `project/adr/0027`, specs/plans 0030–0031 | unchanged (shared monorepo records, with `project/agents/`) |

Development profiles after the move: Lumio runs its native suite and lint
from `products/lumio`; Ariadne Core from its member directory; the root
`pytest`/`ruff` defaults cover the shared coordination tests, the two paired
integration modules and the shared trees only. See
[CONTRIBUTING.md](../CONTRIBUTING.md).

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
