# Single MCP facade server

Status: accepted (owner, 2026-09-14 shaping session).

Agents reach both context (OKF) and metrics (OSI via Datus) through one MCP facade server (`ariadne/serve.py`) instead of connecting to two separate MCP servers (Datus's own server plus a thin OKF server). Owner chose the facade over the recommended two-server topology: one endpoint, one connection, integration mechanics hidden behind it.

**Consequences:** we own the facade's failure modes; Datus integration (Python import vs CLI subprocess) is hidden inside it and decided by the Phase 0 spike.
