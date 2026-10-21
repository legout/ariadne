# lumio-lancedb development notes

Scoped notes for the optional LanceDB enhanced-retrieval adapter. Vocabulary
and decisions: [`../../project/lumio/CONTEXT.md`](../../project/lumio/CONTEXT.md),
[`../../project/lumio/adr/`](../../project/lumio/adr/) (ADR-0010 workspace and
packaging; ADR-0025 repository split with its 2026-10-21 location amendment).
Root instructions and [`CONTEXT-MAP.md`](../../CONTEXT-MAP.md) govern scope
and ownership.

- Validation follows the root suite: focused tests serial, full suite
  `uv run pytest -q -n 4`, never `-n auto`.
- Depends only on `lumio-wiki` with its bounded lockstep range; Torch stays
  behind the optional `embeddings` extra and never enters the base adapter.
- Apache-2.0; the license file sits beside this package.
- The private Lumio web application is excluded (ADR-0025).
