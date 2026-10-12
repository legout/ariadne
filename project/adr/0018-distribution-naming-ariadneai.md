# ADR-0018: Distribution naming — `ariadneai` / `ariadneai-agent`

| | |
| :--- | :--- |
| **Status** | Accepted (owner decision, Pi conversation 2026-10-03) |
| **Context** | [ADR-0012](0012-local-first-artifact-runtime.md), [ADR-0016](0016-modular-core-git-authoring.md) |

## Decision

The PyPI distributions are named **`ariadneai`** (the deterministic core) and
**`ariadneai-agent`** (the separately installed conversational agent). The
import namespaces stay `ariadne` and `ariadne_agent` unchanged.

## Rationale

The owner wanted an `ariadne-ai`-style public name. On PyPI, `ariadne`
belongs to the unrelated GraphQL library and `ariadne-ai` is taken by an
unrelated project; `ariadneai` (the owner's stated alternative) is free and
unambiguous. Renaming only distribution metadata avoids breaking the
`ariadne` import namespace that every plan, ADR and skill pins.

## Consequences

- Installation surfaces (`pip install ariadneai[...]`, agent dependency,
  install hints, READMEs, skill) use the new names; historical
  specifications/plans keep their original `ariadne-core` wording as history.
- Publishing is tag-gated (`.github/workflows/publish.yml`): a `v*` tag that
  equals both projects' versions builds and uploads both wheels; core tests
  run on the built wheel before upload. **Amended 2026-10-12 (owner choice):**
  authentication uses a PyPI account API token via the `PYPI_API_TOKEN`
  repo secret — one token covers both distributions and PyPI creates the
  projects on first upload, so no PyPI-side registration is needed. This
  replaces the originally decided trusted publishing (OIDC); the `pypi`
  GitHub environment and trusted-publisher registrations are no longer
  required.
