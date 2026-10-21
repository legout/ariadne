# lumio-wiki development notes

Scoped public instructions for the Lumio Knowledge Base foundation inside
this monorepo. Vocabulary: [`../../project/lumio/CONTEXT.md`](../../project/lumio/CONTEXT.md).
Decisions: [`../../project/lumio/adr/`](../../project/lumio/adr/) (ADR-0010
workspace/packaging; ADR-0025 repository split with its 2026-10-21 location
amendment). Root instructions and
[`CONTEXT-MAP.md`](../../CONTEXT-MAP.md) govern scope and ownership.

- Machine-specific Knowledge Base operating configuration is **not** part of
  this repository; the imported historical agent guidance is preserved as a
  record in `project/lumio/AGENTS.imported.md`, not as active instructions.
- Validation: run focused tests serially (`uv run pytest -q <test paths>`
  from the repository root); the full suite is `uv run pytest -q -n 4`.
  Never use `-n auto` — a fixed worker count keeps local and CI resource
  use predictable.
- The base wheel stays model-free and cloud-free: model, S3 and MCP
  capabilities live in the optional extras (`documents`, `llm`, `s3`, `mcp`),
  imported lazily. Do not add a base dependency or a downward one.
- Workspace imports are not standalone-wheel proof: keep the isolated wheel
  verifiers meaningful (ADR-0010).
- Apache-2.0; the license file sits beside this package.
- The private Lumio web application is excluded (ADR-0025); nothing here may
  name or require it.
