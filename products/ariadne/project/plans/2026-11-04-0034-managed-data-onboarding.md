# Plan 0034: Managed data onboarding through Pi

**Owner approval — 2026-11-04:** “Approved. lets ticketize” approves this revision, the linked plans and scoped technical refinements, and GitHub ticket publication. It grants no new implementation, tenant/source access, deployment, integration, push or release authority. Tracker: [#85](https://github.com/legout/ariadne/issues/85).

Canonical task bodies now live in the linked GitHub issues; this file owns the interface/dependency/coverage overview, not duplicate task instructions.

Status: **owner-approved implementation plan, revision 1; ticketized**. Date: 2026-11-04. This is the Ariadne-owned plan0034, distinct from the shared workspace plan0034.

## Goal, sources and authority

Let an authorized contributor request a data source, clarify its meaning, review the actual analytics consequences, and obtain a governed or explicitly exploratory result through Pi. Keep credentials, Git, profiles and admission bookkeeping in the owner-managed environment. Cover CSV/JSON/Parquet, XLSX, supported databases and S3 file/table modes; a document conversion is not spreadsheet query support.

Behavioral source: [shared spec0034 revision 3](../../../../project/specs/2026-11-04-0034-agent-first-shared-workspaces.md), §§4–6/10 and AC9–12/AC14/AC16–18. The owner selected all those input categories, stored XLSX values without recalculation, explicit refresh, separate source/data grants, and asked planning to proceed after selecting Entra first. Spec §10's exact bounds, project-grant realization and this decomposition are approved by “Approved. lets ticketize” (2026-11-04). No source access, provider call, fixture service, implementation, deployment, target integration or publication is authorized by the plan.

Retained constraints: [ADR-0024](../adr/0024-git-only-durable-authored-state.md), [ADR-0026](../adr/0026-lumio-sdk-bound-governed-releases.md), [spec0033 revision 1](../specs/2026-10-23-0033-managed-knowledge-authoring.md), [spec0032](../specs/2026-10-22-0032-integrated-query-and-profile-expansion.md) and [data-source reference](../../docs/reference/data-sources.md). Source Approval is distinct from Publication Admission. Native read-only DuckDB catalogs remain operator-trusted backing access, not a sandbox. Keep compile/grain/Policy gates, support/build identities, direct optional SDK consumption and Core-last activation.

Capture: no new domain terms or analytics architecture decision; the shared ADR owns hosting/identity. Spreadsheet extraction creates a derived data source with explicit provenance, not an authored metric or a new storage abstraction. Planning-contract version 1; installed skill provenance unknown. Code inspected at `34bfe1be`; existing approved authoring work is not assumed delivered merely because its plan is approved.

## Sequence, ownership and interfaces

[Shared plan0034](../../../../project/plans/2026-11-04-0034-agent-first-shared-workspaces.md) owns authentication, uploads, browser approval, task persistence, recovery and final W6 qualification. [Lumio plan0011](../../../lumio/project/plans/2026-11-04-0011-document-first-enrichment.md) owns neutral content and enrichment. This plan owns only **D0 → D1 → D2 → D3**, following shared W3; serial ownership avoids conflicting changes to the service, client and Core admission.

Path abbreviations:

- **A** = `products/ariadne/packages/ariadne-data/`; Python package `src/ariadne/`.
- **S** = `products/lumio/packages/lumio-workspace/`, created by shared W1.
- **C** = `products/lumio/clients/pi-workspace/`, created by shared W1.

Approved service adapter: S `src/lumio_workspace/analytics.py`. It lazily imports Core only after explicit analytics enablement. Public operations accept opaque workspace/project/source/task handles, never arbitrary server paths or credentials:

- `prepare_data_source` creates a native proposal with the selected source/table and known business questions; returns pending connection/source/meaning decisions and a browser review URL, not query readiness.
- `profile_data_source` runs only after current workspace permission and exact native Source Approval; returns bounded actual schema/profile facts and their scope, not an inferred business metric.
- `query_data` resolves a current native admitted/pinned execution state, checks the user's authorization for its entire effective source set before constructing a catalog, and invokes the native governed/detail/record/ad-hoc route. Result includes actual governance status, period/units/caveats and complete mandatory context/citations.
- Integrated `prepare_contribution` uses D0's whole-contribution review and one overall native admission. A content-only browser action never conceals a metric change. Contribution review does not substitute for source authorization or admission evidence.

Owner-controlled source connection bindings refer to secret environment/file inputs; neither Pi nor tracked configuration contains credential values. A user without a grant can request access, not borrow the owner's service identity. First-release data access is project/source-set scoped, not arbitrary row-level security: use restricted DB roles/views or separate execution projects for narrower scope. Reuse an unchanged exact native grant without repeated approval; endpoint/scope/definition changes require new evidence/consent. Live data freshness remains distinct from immutable model versions.

## D0 — Satisfy the existing native managed-admission dependency

Canonical task: [#91](https://github.com/legout/ariadne/issues/91). Dependencies: [W3 / #89](https://github.com/legout/ariadne/issues/89).

## D1 — Request, approve, profile and query one real source

Canonical task: [#92](https://github.com/legout/ariadne/issues/92). Dependencies: [D0 / #91](https://github.com/legout/ariadne/issues/91), [W3 / #89](https://github.com/legout/ariadne/issues/89).

## D2 — Upload CSV/JSON/Parquet and selected XLSX sheets as data

Canonical task: [#93](https://github.com/legout/ariadne/issues/93). Dependencies: [D1 / #92](https://github.com/legout/ariadne/issues/92), [W4 / #90](https://github.com/legout/ariadne/issues/90).

## D3 — Use existing database and S3 file/table families through the same path

Canonical task: [#94](https://github.com/legout/ariadne/issues/94). Dependencies: [D1 / #92](https://github.com/legout/ariadne/issues/92), [D2 / #93](https://github.com/legout/ariadne/issues/93).

## Requirement coverage and delivery

| Requirement | Task/evidence |
| --- | --- |
| Shared AC9 truthful data meaning/queryability | D1/D2 and W6 host interaction |
| AC10 independent source and user grants | D1/D3 |
| AC11 whole business/calculation review | D0 native A2; D1 browser/overall admission |
| AC12 standalone products/explicit integration | D1 optional adapter; W6 isolated wheels |
| AC14 governed versus exploratory answer | D1 native pinned queries; W6 |
| AC16 stored XLSX/cache refusal | D2 |
| AC17 S3 target identity/rotation | D3 and native source tests |
| AC18 all selected data categories | D1–D3 plus shared W4/W6 documents |
| Source versions/history, stale consent, recovery | D1/D2 plus shared W4/W5 |
| Existing grain/join/Policy/release invariants | Unchanged native gates; D0/D1 integration |

Required repository CI stays authoritative and is extended for new file selection/optional dependencies, not replaced by repetitive per-task suites. Proposed tests/commands above have not been run. From a repository-root execution environment use Python 3.14 and the intended package/test configuration; no claim that the presently observed Python 3.12 environment satisfies that prerequisite.

Package/skill documentation changes need diff/link/asset inspection, not a new test per paragraph. Existing standalone and same-commit pair wheel checks run at shared W6 when their deltas require it. Public compatibility metadata must name the actual compatible SDK/Core versions at a separately approved release; a source-tree success is not installed-package proof.

Rollback disables the optional service adapter or restores a previously reviewed native admission; it never rewrites historical data/knowledge artifacts or automatically deletes credentials/originals. A new service deployment must not adopt/migrate a live project without its own preview and authorization. No production source, S3 account, permission grant, or private app integration is selected here.

Validation addresses actual uploaded bytes, remote authenticated callers, credential-backed data boundaries, and partial publication—not malicious administrators or hypothetical stolen secrets. Reuse valid evidence, permit one authorized fix pass and one delta recheck, then return unresolved issues to the owner. The sources/dependency amendment are approved and the tasks ticketized; separate execution authority and prerequisite evidence remain required.
