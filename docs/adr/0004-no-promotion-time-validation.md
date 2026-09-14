# No promotion-time validation (MVP)

Status: accepted (owner, 2026-09-14 grill-with-docs round 1) — MVP scope.

We considered validating the staging+served union at promotion time, so a human could never promote a combination of artifacts that does not compile together. Rejected for MVP pace: the Authoring Agent produces artifacts in one batch, the batch is validated as a set before review, and the single user promotes whole batches, so an inconsistent promotion requires actively moving a partial batch. Revisit when authoring batches interleave, multiple authors stage concurrently, or real data is involved.
