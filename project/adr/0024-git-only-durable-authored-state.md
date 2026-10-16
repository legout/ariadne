# Git-only durable authored state

Status: proposed written decision; bounded Core design approved by the owner in the Pi conversation on 2026-10-16, written specification/ADR review pending.

Use the existing native Git branch/worktree and exact-revision human admission route for all durable authored Core artifacts, including document-derived pages and the separate Answer Example directory. Make ad-hoc execution ephemeral; an explicit persistence request uses existing Authoring edits rather than automatically manufacturing a Git draft for every question. The owner selected this over dual staged/Git stores and automatic Git persistence because querying should not leave a second change-management system or unsolicited durable artifacts.

Original documents remain private operator-managed sources; Git carries exact references/digests and derived content, not a new Core-owned upload/archive store. Keep Source Approval separate from artifact review and Git Admission. Common admission of an Example approves only its historical method-reference meaning, never a metric definition or independent numerical attestation.

The owner excluded legacy migration/compatibility because the only data project will be created anew. Retire the old Core routes, but do not delete/reset existing projects or infer production/source-access authority from this decision. This deliberately replaces the retained exceptions in ADR-0003/0005/0009/0013/0015/0016, while preserving the compiler, source, human-review and response-safety boundaries. The observable contract and exact scope are in [specification 0027](../specs/2026-10-16-0027-core-git-only-authoring.md).

No shared Context Provider, ID namespace, release manifest, Lumio source-history API or mandatory-policy failure rule is selected. Those require the joint #76 contract; standalone native Context metadata is not presumed a lossless Lumio export. Ariadne Agent/Tau remain deferred, and neither Core acceptance nor Git admission authorizes software integration, push, release or deployment.
