# Own authoring pipeline instead of leveraging datus-agent

Status: accepted (owner, 2026-09-14 shaping session).

Datus-agent already generates OSI YAML with LLM agents, but we build our own authoring pipeline (profiler + LLM synthesis for both OKF and OSI). The authoring loop — OKF context generation plus compile-error feedback — is the project's differentiating IP; Datus serves only as the compile/execute engine. Leveraging datus-agent's generator would couple MVP pace to their system and leave the OKF context layer unbuilt either way.

**Considered options:** leveraging datus-agent's OSI generation (less code, but no OKF output and a second system's semantics to learn) — rejected.
