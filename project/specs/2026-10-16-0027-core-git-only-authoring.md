# Specification: Core Git-only durable authoring

| | |
| :--- | :--- |
| **Status** | **Approved, revision 1** |
| **Approval** | Owner, Pi conversation 2026-10-16: selected ephemeral ad-hoc execution with explicit persistence only through existing Git Authoring; a separate OKF Example directory with common Git Review Admission; private external originals with exact references/digests in Git. Explicitly excluded legacy work: “Ignoriere legacy projekte. es gibt nur eines, was komplett neu initialsiert/angelegt wird”. Then selected “Core-Design freigeben (Recommended)” for the complete bounded design, including retirement of the persistent upload operation and the unapproved #76 gate. The owner subsequently selected “Schriftliche Fassung freigeben (Recommended)”, approving this complete written revision 1, its concrete interface details, glossary and scoped ADR amendments for implementation planning. |
| **Scope** | `ariadne-data` standalone Git authoring, ephemeral ad-hoc execution, Git-backed Examples and document-derived artifacts, Git-first setup/discovery, retirement of Core staging/Promotion/legacy routes, Core CLI/MCP/packaged guidance/fixtures. |
| **Intake** | [#74](https://github.com/legout/ariadne/issues/74), updated 2026-10-15T20:22:36Z; [#76](https://github.com/legout/ariadne/issues/76), updated 2026-10-15T20:23:30Z. The owner's new-project-only decision supersedes #74's legacy-migration acceptance example for this slice, not permission to delete or reinitialize anything. |
| **Baseline** | Accepted isolated Core #73 candidate `76d9bea9d1129c31dda3cce363c787eb0f072e6a`, Python ≥3.14 / MCP 2.2.0 ([spec 0026](2026-10-15-0026-core-python314-mcp2.md)); target main remains separate. |
| **Decision** | [ADR-0024](../adr/0024-git-only-durable-authored-state.md); vocabulary in [CONTEXT.md](../../CONTEXT.md). |
| **Contract** | planning-contract v1; installed skill provenance unknown. |

## 1. Purpose, scope and non-goals

Complete the existing native Git proposal/worktree route for a newly created Ariadne data project. Git is the only durable revision model for authored source declarations, Seed Notes, OSI models/graph, native Context Layer artifacts, document-derived content/provenance and explicitly saved Answer Examples. There is no application-owned staging tree or parallel persistent draft catalog.

Keep Core independently usable with local Git, without GitHub, a running Lumio service, MCP or Ariadne Agent. DuckDB, SQLGlot, the existing OSI/OKF meaning, independent numerical validation distinctions and human authority remain unchanged. This is a breaking Core interface cleanup with explicit caller replacements, not a second compiler or storage service.

Excluded: migration/import/export/compatibility of legacy projects or their pending files; resetting, deleting, inspecting or admitting the owner's real data project; real source access; Ariadne Agent/Tau/tau-mcp code or compatibility certification; ODCS (#75); publication, rollout and software target integration. Updating Core's packaged skill does not authorize installation into user projects.

The cross-repository parts of #74 remain gated by #76 (§8). Completing this Core slice does not close the full issue or define the external Context Provider contract.

## 2. One Git candidate, one admission route

Reuse the existing project-bound Git Authoring Proposal and Candidate Revision. A candidate is a native branch/worktree and exact Git revision, not a newly named staged object. Existing revision checks, path/type/credential validation, full applicable validation, repair bounds, mapping confirmation and human `ariadne-admit` remain in force.

The complete candidate/snapshot scope additionally includes `answer_examples/` and its necessary generated OKF navigation. Ingest-derived pages and their provenance are ordinary native Context Layer artifacts. Generated artifact bytes are finalized before validation/review; no post-review decoration changes the admitted bytes.

`.ariadne/` may contain derived caches, native-worktree/reference bookkeeping, revision-bound measurement/validation evidence and separate operator approval/admission records. It must not become a second authoritative store of edited business artifacts, Example drafts, uploaded originals or ad-hoc metric proposals. Operational records reference real Git objects; they cannot turn uncommitted bytes or a validator result into reviewed content.

Ordinary public querying resolves the immutable, validated, human-admitted project snapshot. A missing/corrupt/mismatched admission refuses rather than falling back to root `semantic_layer/`, a selected branch or mutable files. Existing connection ownership, source identity/effective endpoint grants, execution deadlines and live grain checks remain binding. Internal numerical tests may exercise lower-level compile/execution seams, but that is not a public legacy serving route.

No new command/tool can approve sources, admit artifacts, confirm mappings, run arbitrary Git/shell/filesystem operations, or submit raw SQL. Authoring/Combined retain the bounded artifact-edit capabilities; Analyst does not gain general Authoring edits. Human local Git review/reconciliation remains distinct from target-branch integration or publication.

## 3. Ephemeral Ad-hoc Metrics; explicit Authoring persistence

`define_metric` retains its existing definition input, static source/SQL authority, grain and single-statement checks, bounded read-only execution, complete result, SQL and definition provenance, caveats and `governed: false`. It no longer reserves names/files, creates a proposal or writes artifacts on success. Failure likewise creates no authored state. Temporary execution machinery is not a durable draft store.

The response removes `staged_as` and `staged_context_as` and adds `persistence: {status: not_saved}`. Existing result/error codes and complete/refused semantics remain; diagnostics referring to staged writes are replaced by truthful no-persistence reporting. The plan must map every affected receipt/error assertion rather than leaving dead staging branches behind. This narrowly supersedes spec 0014's success-before-staging sequence; all collection, byte, refusal and deadline safeguards remain.

There is no `save`/`persist` flag or new save-metric tool. After an explicit request to retain a definition, the harness/operator uses existing Authoring `start` and revision-checked typed `edit` operations to put OSI and associated pages/Policies into an unadmitted candidate. It reuses the existing model representation and validation, not a new query-history or serialization store. Analyst-only MCP can explain this handoff; Authoring/Combined or the local CLI performs the bounded edit. Neither the historical answer nor saving its definition admits a metric.

Fresh retries execute afresh and may see changed data; no automatic retry, saved-answer replay or exactly-once delivery guarantee is added.

## 4. Answer Examples inside the admitted Git snapshot

Retain the separate `answer_examples/` OKF directory, bounded record format, explicit confirmation/business-meaning attestation, SQL provenance, method checking and historical/non-executable meaning of specs 0007/0023. Do not place Examples among Context Layer rules or silently convert them into OSI definitions. Limits remain 8 KiB for the answer excerpt and 64 KiB for the whole encoded record; malformed/oversized input writes nothing.

`save_example` remains a narrow, explicit submission capability, not a general file editor. Without a selected candidate it creates a new unadmitted Git Authoring Proposal based on the admitted query snapshot. An explicitly supplied proposal must also supply its expected revision; the write refuses stale/foreign/conflicted identities. The result identifies the Example ID, artifact-relative path, draft status, proposal and base/candidate revisions. It never returns a fictitious staging receipt or claims the Example was admitted.

Source/result/attestation checks run before the first durable artifact mutation; use the existing Git write/revision discipline. A Git/I/O failure names any observed unadmitted residue and never claims rollback or automatic admission. Lost delivery can leave an actual candidate; do not blindly retry and create duplicates. IDs remain explicit file identities, never fuzzy question matching; no global/shared #76 ID scheme is introduced.

Common full-candidate validation/review/admission replaces `ariadne-example-review`. The human must still inspect the Example's explicit attestation and technical/provenance evidence. Review/admission actor/time and exact-revision evidence must not be fabricated by authored metadata or added by changing artifact bytes after validation. A candidate file declaring itself stable/verified remains unadmitted; views derive admission from the bound snapshot, not that string.

A new/edited Example must have resolvable matching metric/Policy dependency digests for the candidate it is submitted to; drift refuses validation rather than silently rewriting historical evidence. Previously admitted, unchanged Examples whose dependencies later change remain historical/stale and are excluded from normal method reuse. A new admission must not relabel those old records fresh. Re-review requires an explicitly revised record; fresh execution and current method/scope checks remain mandatory.

Default `search_examples` reads the admitted snapshot only. Draft discovery reads an explicitly selected project's candidate Git revision, returns that revision and an unambiguous unadmitted label, and never scans all branches or a staging directory. `include_history`/`include_sql` retain their separate meanings and bounds. Examples never enter governed `get_metric.context`; default context/discovery must not mix in a candidate. Existing candidate artifact reading remains available to Authoring; read-only Context browsing may explicitly select a candidate with the same labeling/path bounds, never for executing governed queries.

## 5. Ingest and private originals

`ariadne-ingest` writes derived pages/provenance into an explicitly selected Git candidate, using the existing supported converters and normal distillation or `--verbatim` behavior. A mutation requires project, proposal and expected revision; there is no default `staging/` destination or implicit mutable-root write. MCP stays project-bound at launch. No new ingest MCP tool or model provider dependency is required.

Retain exact converted-text preservation for Verbatim, ordinary opt-in reconciliation/Policy egress, per-type metadata/credential checks, bounded payloads, no overwrites, source digests and truthful partial-batch outcomes. Idempotence compares against the selected candidate, not a separate ingest ledger: unchanged source/content at the current expected revision can be an explicit no-op; a stale expected revision still refuses. Changed content makes a separately reviewable change; it never rewrites an admitted snapshot or silently replaces unrelated edits. A failed batch reports which committed candidate changes actually occurred and the resulting revision; do not promise an all-or-nothing batch transaction that the existing route lacks.

Original document bytes remain private, operator-managed sources outside the authored Git artifact set. Reuse Ariadne's existing native document resource/digest representation and the separately operator-managed allowed local roots/exact approved object URIs. A candidate's `documents:` declaration, a Git commit or artifact admission cannot widen the host permission list. Native local references do not become portable Lumio/ontology IDs by assumption; §8 owns that future binding.

Document reads/conversion capture the digest and derived text from the same bounded source-byte snapshot. Missing access, unavailable bytes, unsupported conversion or a mismatched required digest is an explicit unavailable/refused outcome, not verified evidence. Do not fetch unapproved references, search the filesystem for replacements, follow credentialed URLs or silently substitute a newer original. Existing source/credential isolation remains binding. Git metadata does not itself prove that a private source remains available or unchanged.

Retire `store_upload`/`AuthoringProject.upload_document` and the persistent `authoring_upload_document` MCP operation, plus app-owned retained-original object copies. Their replacement is operator placement in an already allowed private input location and reference-based evidence/ingest; no new Ariadne upload/archive/history service is introduced. Required converter scratch files are temporary and cleaned up, not restart-readable draft/source stores. No existing user source copies are deleted by implementing this retirement.

## 6. Git-first setup, diagnostics and explicit retirement

New `ariadne-init`/`ariadne setup` scaffolds for Git Authoring only, without creating `staging/`. Preserve collision/path/no-overwrite checks, filename-only inert source suggestions, optional explicit skill wiring and read-only status. Setup still does not run `git init`, set Git identity, open sources, approve access, admit content or initialize the owner's real project. Missing Git/repository-local identity yields the existing human prerequisite handoff.

Remove the legacy staged/bundle submit/Promotion, separate Example-review and legacy serving implementation paths and installed entry points. Retired selectors such as `--legacy`, `--served`/`--staging` for public serving cannot select an unreviewed artifact root. If an umbrella parser retains a refusal for an old spelling, it fails before mutation and points to Git-first setup; there is no compatibility implementation behind it. Public Python callers use project-bound admitted runtime construction; plain-root aliases cannot remain a hidden governed-query bypass. Retain local CLI/Python capability and optional MCP, not legacy argument compatibility.

Status/review/discovery describe Git proposals, matching validation/admission and Examples rather than a staged backlog or Promotion destination. Source-free discovery/status remains source-free, including before a catalog/admission. Reading a candidate for review does not activate it. Existing context-only admission remains possible without invented metrics or measurement claims.

The plan maps affected Core callers, CLI/MCP schemas, examples, generated guidance, packaged skill and fixtures to retained/replacement/removed surfaces. Port synthetic numerical fixtures to the new public route or their proper lower-level test seam; preserve independently defined numerical expectations and safety scenarios. Remove dead legacy code/tests only after replacement checks cover still-supported behavior. Do not preserve a legacy runtime merely to make old fixtures pass, and do not delete a numerical/security requirement because its former fixture used staging.

There is no legacy migration inventory, export command, transitional read-only server or automatic archive/delete/reset. The owner will arrange a new project separately. Existing user files and approval records outside the synthetic test fixtures are untouched.

## 7. Observable acceptance criteria

1. **AC1 — Git-only durable artifacts:** in a synthetic fresh project, existing Authoring operations put source declarations, model/Policy/Seed Notes and ingested pages into native Git candidates. Full applicable validation covers inherited and changed bytes plus Examples/navigation. No artifact draft, Example or retained original appears in application-owned staging/proposal/upload stores. Operational evidence/permissions cannot confer artifact admission.
2. **AC2 — Ephemeral querying:** successful and refused `define_metric` calls create no durable candidate/artifact, retain correct independently specified rows/SQL/definition/governance/complete-output semantics, and report not-saved without staging paths. Explicit existing Authoring edits retain the requested definition in a Git candidate; it is not queried as governed before human admission.
3. **AC3 — Example lifecycle:** no confirmation stores nothing; an explicitly confirmed bounded submission creates a draft Example in Git. Default search sees only admitted Examples; explicit candidate search immediately sees it as unadmitted with its revision. Common human Git Admission makes it reusable as a reviewed method, never a metric or cached answer. Forged review strings, stale/foreign revisions, invalid provenance and oversize input refuse. SQL opt-in/history, dependency staleness, historical retention and fresh execution remain correct.
4. **AC4 — Ingest/identity:** normal and Verbatim ingestion into a named candidate retain their existing conversion/content/consent bounds and exact source digests. An unchanged candidate/current-revision retry is a no-op; stale revision, conversion/credential/path failure or changed source cannot silently overwrite or assert an old digest. Source bytes and digest derive from one snapshot. Honest partial-batch outcomes identify actual Git changes; no staging-ledger fallback exists.
5. **AC5 — Private source boundary:** original files/objects remain external operator-owned inputs, with no durable Core upload/retention copy. A proposed source/root/URI cannot grant access; unapproved, missing or digest-mismatched inputs refuse before unrelated reads/writes and disclose no credential values. No project reset/deletion or production source access is part of verification.
6. **AC6 — Snapshot/governance preservation:** governed CLI/Python/Analyst/Combined calls use one immutable exact admitted snapshot with matching Source Approval/effective endpoints. A later candidate/worktree edit, missing admission, stale evidence, unsafe grain, changed required candidate Policy or unauthorized source cannot silently change/admit its answer path. Golden/money/window/multi-fact/source-containment/limit/deadline/quality-caveat expectations remain unchanged; no new missing-Policy runtime refusal is inferred from #76.
7. **AC7 — Retirement and adapters:** Git-first setup/status/review/source-free discovery and explicit candidate browsing work without MCP/GitHub/Lumio. Legacy selectors and retired operations cannot mutate or serve legacy state. Core CLI/MCP/packaged guidance and synthetic fixtures match the new behavior, with no approval/raw-SQL/general-file tool expansion. Agent/Tau files remain unchanged and their compatibility remains unverified.
8. **AC8 — Honest handoff:** the isolated Core candidate records exact commit/tree, focused and full relevant Core checks, independent review and unavailable claims. It explicitly leaves #76's shared profile/provider/manifest work and the original full #74 incomplete. No target integration, push, issue closure, release, deployment or real project initialization is claimed.

Use focused new checks at the existing public seams for no-persistence, Git-backed Example admission/staleness and candidate ingest/private-source refusal. Expected values come from existing independent fixtures and these criteria. Reuse the established golden, containment, source/admission, mapping, format/size/deadline and real stdio/HTTP checks. Detailed tasks/commands and one assigned test obligation per validation unit belong to the subsequent approved plan, not a second checklist here.

## 8. Joint #76 gate; accepted source reconciliation

No Context Provider methods/envelope, shared namespace/entity/Policy/ODCS/model ID scheme, cross-component admission/release manifest, Lumio activation semantics or mandatory-policy failure contract is defined here. The native standalone Context reader and Ariadne-specific schema/mapping metadata remain; generic Lumio OKF export is not assumed lossless. A replaceable external provider is a later jointly approved interface, not a new abstraction added speculatively during this cleanup.

Lumio's approved component source `f4d1139d7a3381dde0f8d1741f5316ae6f9eadc0` (spec 0008 r2 / ADR-0029) owns its Git Source Reference Manifest and private source-history contract. It is read-only design context here, not a dependency on its unfinished runtime or approval to copy its fields into an Ariadne ABI. The Lumio peer confirmed no approved #2/#76 binding/provider design as of 2026-10-16. That gate blocks consuming/claiming those shared interfaces, not this standalone Core lifecycle.

In particular, [ADR-0011](../adr/0011-context-carrying-answers-and-skill.md) and [spec 0011](2026-10-06-0011-context-trust-signals.md) currently permit unavailable required context to return `context: null`/`context_unavailable` without failing a query. This remains unchanged here. Rejecting an invalid candidate at validation is not a silent change to that runtime rule; #76 needs an explicit coordinated amendment before requiring a different failure path.

This approved revision makes only the following scoped supersessions; original approval records and unaffected behavior remain intact:

| Owning sources | Scoped replacement |
| --- | --- |
| ADR-0003/0005/0009/0013/0016; specs 0001/0005/0009 | Retained local staging/bundle/Promotion and legacy serving/compatibility become the new-project-only native Git route; private document permissions and deterministic/human gates remain. |
| ADR-0015; specs 0007/0023 | Separate Example meaning/folder/consent/SQL/staleness retained, but storage/review/default draft discovery use Git candidates and common admission. |
| ADR-0019; spec 0014 | Query output/deadline/authority safeguards retained; successful ad-hoc execution becomes ephemeral, with no reserve/stage phase or staging receipt. |
| Specs 0002/0015/0018; ADR-0020 | Retrieval content/ranking/path bounds retained; no default staging source, and explicit Git candidate views are always unadmitted. |
| Specs 0016/0017/0019; ADR-0021 | Git-only setup/status/review reporting, without legacy route choice or Promotion branch; source-free and human-only boundaries retained. |
| Spec 0021 | Conversion/Verbatim/consent/idempotence/no-overwrite retained with candidate Git identity rather than staging identity. |
| Spec 0025 | Named scoped S3 profiles, secret isolation, effective endpoint grants and all retained-format checks unchanged; legacy staging-compatibility obligations alone retire. |
| Spec 0026 | Python/MCP versions, optional packaging, bounded framing and HTTP safeguards remain; this later design explicitly changes only named persistence/candidate-selection/retired-operation contracts, not SDK alignment. |

## 9. Capture checkpoint and handoff

- **Vocabulary:** the isolated glossary expands Authoring Proposal to explicit document-derived artifacts and Examples; Staging/Promotion/ad-hoc Proposal become historical route terms. Ad-hoc Metric remains ungoverned; admission does not become independent numerical validation. No joint #76 vocabulary is invented.
- **Decision:** ADR-0024 records Git-only authored state versus dual stores/automatic Git drafts and private external originals versus Git blobs; it explicitly retires legacy compatibility by the owner's decision. Existing ADRs/specifications carry scoped amendment notices rather than rewritten approval history.
- **Behavior:** the complete bounded in-chat design and this concrete written revision 1 with its amendments are owner-approved; the written approval was “Schriftliche Fassung freigeben (Recommended)” on 2026-10-16. The original request supplies supervised execution direction, but no #74 writer starts before written specification/plan approval and current readiness verification.
- **Uncertainty:** no remaining product choice is assumed for this bounded Core slice. Repository-wide caller mapping, removed-entry-point behavior, exact same-revision Example validation and private source availability need planning/verification. Shared #76 identity/binding/failure semantics remain unresolved and explicitly excluded. New-source/source-reset/deployment actions need their own authorization.
- **Handoff:** planning-contract v1, installed provenance unknown; accepted #73 candidate is the base, not a merge into main. After written approval, prepare the smallest sequential plan with isolated Pi writers and independent validation. No new ticket, external ABI or duplicate proposal ledger is authorized by this capture.
