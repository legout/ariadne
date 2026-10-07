# Implementation plan: Local-first artifact runtime

> **Historical status — 2026-10-07:** Historical execution map: #7–#9 are closed. The original approvals, compatibility seams and gates below are capture-time history, not a new execution authorization. Later modular-core constraints govern changed interfaces.

| | |
| :--- | :--- |
| **Status** | **Approved — ticketized** |
| **Goal** | Make promoted Ariadne artifacts fully usable through a local JSON CLI while retaining MCP as an optional adapter over the same runtime. |
| **Source** | [`project/specs/2026-09-23-0001-local-artifact-runtime.md`](../specs/2026-09-23-0001-local-artifact-runtime.md) |
| **Source approval** | Owner, pi session 2026-09-23 — complete design and written specification approved; exact scope is the specification header’s approved scope. |
| **Plan approval** | Owner, same session — three-task decomposition and validation strategy approved for later execution. |
| **Decision** | [`project/adr/0012-local-first-artifact-runtime.md`](../adr/0012-local-first-artifact-runtime.md) |
| **Contract** | planning-contract v1; installed skill provenance unknown |

## Constraints and assumptions

- Preserve the compiler, single-statement guard, bind check, grain guard, read-only execution, context attachment, proposal staging, and human-promotion behavior.
- `AriadneRuntime` is the single behavior owner; local CLI and MCP are adapters only.
- Preserve `from ariadne.serve import Facade` compatibility.
- Do not migrate the existing author/profile/validate/promote/ingest commands into the umbrella CLI.
- Local definition JSON and artifact files are user-owned inputs. No new remote trust boundary is introduced; the existing accepted agent-authored SQL boundary remains compiler- and read-only-gated.
- Use the existing Python 3.12, argparse, DuckDB, sqlglot, PyYAML, pytest, and ruff stack; add no dependency.

## Capture checkpoint

- **Vocabulary:** “runtime” is defined by the approved specification; no glossary file is needed.
- **Decisions:** ADR-0012 records local-first execution and optional MCP.
- **Behavior:** the approved specification owns scope, non-goals, interfaces, failures, compatibility, and acceptance.
- **Uncertainty:** none material. Execution still requires owner authorization.

## Canonical tickets

Ticket bodies own the executable task definitions; this file is only the dependency and requirement-coverage overview.

| Order | Ticket | Scope | Specification acceptance | Dependency |
| :--- | :--- | :--- | :--- | :--- |
| 1 | [#7 — Extract the transport-neutral Ariadne runtime](https://github.com/legout/ariadne/issues/7) | One runtime implementation plus `Facade` compatibility and MCP adapter reuse | AC 1–3, 9 | Approved spec and ADR |
| 2 | [#8 — Add the local JSON CLI and optional MCP packaging](https://github.com/legout/ariadne/issues/8) | Five local operations, root discovery, JSON contract, base/MCP packaging split | AC 1–10 | Blocked by #7 |
| 3 | [#9 — Make project and agent guidance local-first](https://github.com/legout/ariadne/issues/9) | Init, packaged/generated skills, README, demo, full integration acceptance | AC 11–12 and final integrated verification | Blocked by #8 |

AC 1–3 and 9 intentionally cross tickets #7 and #8: #7 preserves the transport-neutral behavior and MCP compatibility; #8 proves the same behavior through the new local interface and base installation.

## Execution and integration

Execute #7 → #8 → #9 sequentially. Each ticket names its owned surfaces, consumed and produced interfaces, test obligation, focused checks, completion evidence, and non-goals. #9 owns the final full-suite, isolated base/MCP installation, and skill-driven acceptance gates.

One candidate review after #9 covers the integrated diff. Allow at most one authorized fix pass and one delta-only recheck; unresolved blockers return to the owner.
