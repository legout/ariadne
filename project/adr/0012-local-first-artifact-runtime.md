# Local-first artifact runtime with optional MCP

Status: accepted (owner, 2026-09-23 shaping session).

Ariadne's governed behavior will live in a transport-neutral runtime used directly by a local JSON CLI and, optionally, by the MCP adapter. Local artifact use is the default because agents already run beside the promoted OKF/OSI artifacts and do not need a server transport; MCP remains useful for remote or host-integrated tool registration but moves to the `ariadne[mcp]` extra. This supersedes ADR-0002's choice of MCP as the sole consuming-agent endpoint while preserving its single-adapter topology when MCP is used.

**Considered options:** a thin CLI importing the facade from `serve.py` was rejected because it keeps the core conceptually owned by an optional transport; skill-authored direct SQL was rejected because it duplicates and can bypass compilation, grain, context, and staging rules.

**Consequences:** the local `ariadne` command and MCP tools must remain adapters over one runtime; the base package cannot import MCP; existing `ariadne.serve.Facade` consumers retain a compatibility alias; initialization and skills teach local usage first.
