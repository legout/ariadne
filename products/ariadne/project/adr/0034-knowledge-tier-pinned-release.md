---
status: proposed
amends: ADR-0026
---

# ADR-0034: Knowledge changes are served unreviewed; the release pins bound pages

[Spec 0042](../../../../project/specs/2026-11-24-0042-knowledge-changes-review-revert.md)
splits authored changes into knowledge changes and calculation changes. A Bound
Release keeps pinning the pages its authority rests on: required Policies,
metric and Computation pages, and structured References. Ordinary pages are
served from the knowledge version Ariadne last committed for serving, flagged
`unreviewed` until a human countersigns their exact content and source
bindings. Governed numbers never depend on an ordinary page.

Publication of ordinary pages rests on the operator's standing, revocable
grant per project; the first publication of a project is confirmed by a human
for exactly what it serves. Countersignature is a separate, always human act.
Readers resolve ordinary pages through Ariadne's one served record, so nobody
observes a half-switched state and a native Lumio `current` is never adopted
directly. This was
chosen over re-admitting the release on every knowledge publication, which
would make admissions automatic, and over pinning everything, which would keep
unreviewed text out of every answer, contrary to umbrella spec 0037. It
narrows [shared ADR-0029](../../../../project/adr/0029-lumio-owned-context-layer.md)'s
"no moving-latest" rule and spec 0035 AC6 to pinned pages, and needs an
explicit amendment of Lumio's
[ADR-0029](../../../lumio/project/adr/0029-git-native-knowledge-authoring.md)
(per-publication Publication Admission) for integrated projects. Visibility
Scope, original retention and refusal before SQL on missing required Context
are unchanged.
