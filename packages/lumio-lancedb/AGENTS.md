# lumio-lancedb development notes

Scoped notes for the optional LanceDB enhanced-retrieval adapter. Vocabulary
and decisions: [`../../project/lumio/CONTEXT.md`](../../project/lumio/CONTEXT.md),
[`../../project/lumio/adr/`](../../project/lumio/adr/) (ADR-0010 workspace and
packaging; ADR-0025 repository split with its 2026-10-21 location amendment).
Root instructions and [`CONTEXT-MAP.md`](../../CONTEXT-MAP.md) govern scope
and ownership.

- Validation follows the root suite: focused tests serial, full suite
  `uv run pytest -q -n 4`, never `-n auto`.
- The SDK is its only sibling dependency, bounded by the lockstep range; on
  top of it the adapter's actual runtime dependencies are `lancedb`,
  `pyarrow` and `msgspec[yaml]`, with the optional `embeddings` (Torch stays
  behind it, never in the base adapter) and `s3` extras.
- Apache-2.0; the license file sits beside this package.
- The private Lumio web application is excluded (ADR-0025).
