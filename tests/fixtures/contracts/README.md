# Contract test fixtures (issue #77/C1, spec 2028 §2)

Both files are exact unmodified official upstream bytes from the ODCS
repository at the pinned commit `f0bdad95346905d500be5ef4b2c2d9b1d95223b7`
(tag v3.2.0). They are independently sourced oracles, not generated output;
their byte identities are asserted in `tests/test_contracts.py`. The local
`.odcs` extension keeps the pinned bytes free of any tool reformatting; the
upstream paths below carry their original `.odcs.yaml` names.

| File | Upstream path | SHA-256 |
| :-- | :-- | :-- |
| `official-authoritative-definitions.odcs` | `docs/examples/authoritative-definitions/authoritative-definitions.odcs.yaml` | `da549b51a2887ee3ac95772a169004e9db455fc47c6795eaa0b9e73b906b9676` |
| `official-full-example.odcs` | `docs/examples/all/full-example.odcs.yaml` | `7a82af5da8d18962031c3a01b2706b6991dce7bd111e5fb9e0a3b214739e1031` |

The first is the official v3.2.0 fixture expected to validate under the
packaged schema pin. The second is the official full example that carries the
same-contract shorthand reference `receiver_types.type_code` naming a schema
object the document does not declare — pinned upstream proof of the distinct
dangling-internal-reference semantic check (upstream CI validates structure
only, so the official example legitimately ships that unresolved reference).
