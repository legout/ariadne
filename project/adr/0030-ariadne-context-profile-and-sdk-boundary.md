---
status: accepted
amends: ADR-0026, ADR-0029
---

# ADR-0030: Native Ariadne Context Profile through an additive SDK

Owner-approved direction, Pi conversation 2026-10-18 for Lumio #2/Ariadne #76:
one Content Repository, direct optional Python SDK, integrated-only strict
mandatory Policies, one overall human confirmation and project-wide Visibility
Scope defaulting to public. The owner selected “Design freigeben (Recommended)”
for the six-section V1 design and its capture in both repositories.
[Specification 0009](../specs/2026-10-18-0009-ariadne-context-profile.md)
contains the written behavior and was subsequently approved with “Schriftliche
Fassung freigeben (Recommended)” on 2026-10-18, together with both specifications,
ADRs, glossaries and scoped source amendments. This opens planning; execution
and publication remain separately gated.

Add an explicitly versioned native Ariadne application envelope and immutable
SDK view. Lumio owns curated Policy/term/Claim content and exact knowledge
identity; it does not own executable OSI, database observations, Source Approval,
measurement authentication or numerical governance. Preserve the supported
native metadata rather than canonicalizing it through lossy OKF interchange.
This is the specific third-party application-profile decision anticipated by
ADR-0026, not a redesign of generic Exchange Profile 1/2.

The consumer uses the exact admitted local/S3 Published Version and verifies
namespace, fingerprint, manifest/source-reference digests, profile and operator
Visibility Scope. Mandatory Policy Closure uses explicit typed Entity references,
not aliases, provenance Sources or navigation. Native Source privacy and
Publication Admission from ADR-0029 remain unchanged.

## Alternatives and consequences

Direct SDK consumption is selected over a profile-bundle intermediary and a
Provider service: one producer implementation and no new runtime service, at
the cost of explicit integrated SDK/build compatibility. Lumio's base package
must not import or depend on Ariadne, SQLGlot or DuckDB, and plain/exchange SDK
contracts remain additive and unchanged.

The shared Content Commit provides a single reviewable business revision.
Ariadne's final admission descriptor is the integrated activation authority;
Lumio's standalone pointer remains independently meaningful. Reusing native
admissions avoids a distributed transaction and a second proposal system.
A completed Lumio publication can remain after failed overall activation and
must not be misreported as an active integrated release.

Native helpers must preserve supported profile metadata or refuse unsafe
rewrites. The private application remains excluded; no software release,
private adoption, production migration or shared-KB publication follows from
the public profile design.
