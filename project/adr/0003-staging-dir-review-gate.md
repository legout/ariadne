# Staging-dir review gate instead of PR flow (MVP)

Status: accepted (owner, 2026-09-14 shaping session) — MVP scope; supersede with the PR gate post-MVP.

The research study (§8) defines the human review gate as pull requests. For the MVP the gate is a `staging/` directory: the Authoring Agent writes there, and a human promotes artifacts by moving files. Chosen for pace: single-user PoC, no reviewers to coordinate, and the audit trail is unnecessary against synthetic data. The PR gate and the `verified` state machine return when the system touches real data or multiple users.
