# Staging-dir review gate instead of PR flow (MVP)

Status: accepted (owner, 2026-09-14 shaping session; single-user real-document scope clarified by owner, 2026-09-23).

The research study (§8) proposes pull requests as the human review gate. For a single-user local project, including real documents ingested under ADR-0009, the gate remains `staging/` followed by explicit human Promotion: no agent may directly serve a proposal. Promotion already appends `verified` history and updates the bundle log (ADR-0007); it is not deferred until real data arrives. A PR gate becomes appropriate when multiple authors or asynchronous approvals require review of a durable exact change set. This preserves the lightweight local flow without treating an LLM suggestion as approval.
