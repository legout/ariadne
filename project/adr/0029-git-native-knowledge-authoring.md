---
status: proposed
amends: ADR-0007, ADR-0008, ADR-0010, ADR-0014, ADR-0015, ADR-0016, ADR-0019, ADR-0020, ADR-0021, ADR-0024, ADR-0026
---

# ADR-0029: Git-native Knowledge Authoring, Separate Publication Admission

Design direction approved by the owner in the 2026-10-15 Pi conversation for
[issue #1](https://github.com/legout/lumio-wiki/issues/1), after choosing explicit
local publication authorization, operator-confirmed Git export of pending
proposals, and a temporarily KB-read-only private application. **Written revision
1 is proposed for review; implementation and integration are not authorized by
this ADR.** Behavior and acceptance belong to
[specification 0008](../specs/2026-10-15-0008-git-native-knowledge-authoring.md).

Git branches/worktrees and native diff/review become the only persistent
Knowledge Base authoring lifecycle. A stored Ingest Proposal, pending source
transition tied to a proposal, or application-owned merge/review state machine
must not survive as a second path. Deterministic ingest and repair helpers may
edit an explicitly selected authoring worktree; Git owns history and conflicts.
Local Git is sufficient. GitHub, signed tags, and an additional database are
not prerequisites.

Publication Admission is a separate explicit authorization of the exact reviewed
revision, source references, validation identity, destination, and expected
active version. A commit, merge, passing validation, frontmatter lifecycle, or
agent assertion is not that authorization. Preview is stateless; admission
records are publication receipts, not draft/change-management records. One
fully prepared immutable Published Version is activated conditionally; private
source history never changes an already resolved Reader Snapshot.

Private source bytes and immutable Source Versions remain outside Git. A
Git-versioned Source Reference Manifest records author-approved exact bindings
and source lifecycle intent without private storage keys or credentials. It is
authoring input, not deployment configuration or Reader content. Its digest is
bound to publication; it does not enter the existing canonical Compiled Page
fingerprint. Publication never resolves a reviewed binding through the
registry's subsequently latest version.

## Scoped amendments

Upon written approval, this ADR replaces only the following target contracts;
the legacy implementation remains governed by its existing operating guidance
until the coordinated implementation is accepted:

- ADR-0007/0008/0010/0015/0016/0024/0026: staged import, maintenance, rename,
  migration, ingest, proposal persistence, and custom proposal publication become
  ordinary Git edits, reviewed and validated before publication.
- ADR-0014/0020: private Source Version and artifact retention/inspection remain;
  source lifecycle intent and exact reviewed references are Git inputs, not
  proposal-bound pending transitions or a publication-time lookup of latest.
  Private publication binding manifests remain private and historical.
- ADR-0021: stable Entities, Claims, Evidence anchors, redirects, ontology,
  graph scopes, and authorization-before-expansion remain. Unaccepted candidate
  assertions live in an unadmitted Git revision, not a persisted proposal.
- Specification 0006's disjoint-proposal publication rule is replaced for the
  new authoring route by native Git reconciliation and expected-current
  activation. No custom auto-merge is retained.

ADR-0013's immutable S3/CAS protocol, ADR-0022's retired Activity Log production,
ADR-0025's repository/package split, ADR-0027's approval workflow, and
ADR-0028's read-only MCP boundary remain. This ADR does not approve Ariadne's
Context Provider, namespace mappings, or governed-query integration.

## Alternatives and consequences

- Keeping proposals behind Git wrappers would preserve two competing sources of
  review/conflict truth and fails the owner's Git-only requirement.
- Signed release tags can express authorization but impose key/trust management
  on standalone local use; explicit local confirmation is the chosen first path.
- Direct publication of any valid branch loses the independent admission
  boundary and was rejected.

The change breaks proposal-facing CLI/SDK contracts and requires an explicit
legacy export path. The private application is an observed consumer, not a
hypothetical one: its isolated transition candidate must pin old wheels and
refuse KB writes server-side before API retirement can be considered safe.
There is no new Git Workshop in this scope, no release approval, and no target
branch integration authority.
