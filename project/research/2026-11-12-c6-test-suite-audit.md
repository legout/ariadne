# Production-relevance test audit — frozen C6 snapshot

Date: 2026-11-12. Status: **completed static audit; recommendations only**.
Audited commit: `d351aae1e1eda411f1bfb52d2ddb667ff867a662`.

## Decision

**Accept the audit; fix-first for test quality, not a C6 acceptance verdict.**
Most of the suite protects real production behavior. The evidence does not
justify wholesale deletion, an end-to-end-only policy, or a target reduction
percentage. The larger problem is tests with stale setup, non-discriminating
fixtures, or assertions that cannot detect their advertised failure.

Concrete pruning candidates:

- **3 whole tests are obsolete for this public product/approved cutover.**
- **11 whole-test consolidations**, subject to retaining the exact assertions
  identified below; one additionally repairs the retained negative fixture.
- **1 repeated refusal block** can go without deleting its numerical test.
- **4 Activity Log generation tests are retirement candidates**, but require
  coordinated disposition of the residual public writer and required verifier.
- A few obsolete individual assertions should be removed/replaced. No entire
  test directory or substantive numerical/permission/persistence suite should go.

These are source-backed recommendations, **not deletions already performed**.
No product tests, collection, imports, builds, installs, services or providers
were run. No test/source files or GitHub issues were changed. The running C6
worker's changing checkout was not audited or redirected. Some observations
fall in its already-known D2/D3 repair families; this report does not establish
which have since been fixed or impose another C6 review/fix round.

## Scope and method

The owner selected **C6 snapshot** and **parallel read-only Pi reviewers**.
A detached, registered snapshot was created at
`/home/volker/.local/state/worktrees/ariadne-eb414525c826/test-audit-20261112`.
It remained clean during the review. Six fresh Pi reviewers used
`openai-codex/gpt-6.1-sol/high`, read/bash tools, complete inline guardrail
contracts, and no product-write or execution authority. Parent inspection
verified the actionable pruning cases and representative repair evidence.

The final inventory contains **160 tracked test/support/verifier files**,
including **2 TypeScript test files**. Static Python AST inventory found
**2,286 named test functions**, not collected or parameter-expanded test cases.
Five explicitly selected integration modules do not begin with `test_`; they
were added to the initial inventory and fully reviewed. A final whole-tree
static scan found no unassigned Python `test_` definitions or other JS/TS
test-like paths. Four shared fixture helpers and CI/configuration were also
inspected. Every assigned file has a disposition in the appendix.

| Area | Files | Static Python test definitions |
| --- | ---: | ---: |
| Core native Context/authoring and nonstandard integration modules | 21 | 240 |
| Core numerical/runtime/source/CLI behavior | 27 | 362 |
| Graph/retrieval/LanceDB/evaluation | 28 | 451 |
| Lumio authoring/intake/source/privacy | 27 | 510 |
| Lumio CLI/S3/setup/product facade | 35 | 635 |
| Workspace/Pi/packaging/shared integration | 22 | 88 |
| **Total** | **160** | **2,286** |

Written criteria: canonical `agent-guardrails`, repository/package AGENTS,
[frozen approved spec0035 r2](https://github.com/legout/ariadne/issues/108#issuecomment-6768381795)
and [spec0034 r6](https://github.com/legout/ariadne/issues/85#issuecomment-6768381020),
and applicable product specs/ADRs.
In particular: [ADR-0022](../../products/lumio/project/adr/0022-retire-activity-log-artifact.md)
retires new Activity Logs; [ADR-0025](../../products/lumio/project/adr/0025-repository-split.md)
excludes private-application tests. Core's breaking native-Context cutover
**does not retire standalone Lumio APIs, Legacy Flat reading, generic OKF,
optional adapters, historical versions or supported legacy-file recognition**.

Production context: local SDK/CLI governed metrics and knowledge authoring,
optional retrieval/conversion, installed wheels, and authenticated Workspace/Pi.
A small parser/numerical unit with an independent expected value can protect
production better than another long journey. Fake external I/O is legitimate
when the real production wrapper is exercised. Similar helpers, small size,
mock use, failure, or a name containing `legacy` do not justify deletion.

Paths and line numbers below refer to the frozen commit, not current `main`.
Abbreviations:

- A = `products/ariadne/packages/ariadne-data/tests/`
- W = `products/lumio/packages/lumio-wiki/tests/`
- L = `products/lumio/packages/lumio-lancedb/tests/`
- T = `products/lumio/tests/`
- I = `integration/tests/`

## 1. Retire these three obsolete whole tests

| Test | Why obsolete / written authority | Protection to keep |
| --- | --- | --- |
| A `test_serve.py:470` — `test_missing_metric_page_collapses_context_without_failing` | Requires a successful `governed: true` calculation without required metric Context. Spec0035 §5/AC7 replaces that warning-only success with refusal before SQL. | Native missing/corrupt/mixed Context refusal, correct admitted numerical answers and optional/advisory freshness behavior. |
| A `test_serve.py:489` — `test_unresolvable_policy_reference_collapses_context_without_failing` | Requires the old classic required-Policy-resolution fallback to succeed. That serving backend and successful fallback are retired by spec0035 §§5–6. | Exact required Policy Closure and refusal/non-mutation. Do not turn optional links or expired advisory facts into required Policies/fatal errors. |
| W `test_okf.py:66` — `test_legacy_okf_module_aliases_the_new_owner` | Checks private `lumio.core.okf` alias identity, only if the excluded private app is installed. ADR-0025 explicitly moves application re-export tests out of this public foundation. | `test_okf_export_and_import_use_only_portable_foundation`; public portable OKF behavior. Remove the unused private-app availability helper with the test, not the public interchange suite. |

The native protections are present in existing tests, not hypothetical
replacements: I `lumio_metric_mvp.py::test_corrupt_missing_or_mixed_release_refuses_before_sql`
forbids source/SQL construction and corrupts actual pinned Policy bytes;
`::test_hidden_required_policy_cannot_activate` preserves prior descriptor bytes
and the prior admitted Policy; I `lumio_local_context.py` has missing physical
Context and completeness-before-planner/bind cases. Existing successful release
and freshness tests preserve correct answers with honest advisory warnings.
These cover distinct boundaries; they are not claims of runtime success here.

Also retire the obsolete `ariadne-ingest` item in A `test_init.py::CONSOLE_SCRIPTS`,
not the supported-entry-point test or currently used document converters.
A `test_git_authoring.py::test_an_unparseable_draft_model_is_a_recoverable_validation_error`
should lose its retired classic `index.md`-only commit expectation, not its
recoverable-draft/error assertions. Native browsing must not demand a classic
untitled glossary page; preserve its useful metadata/read/path checks.
Three unused classic fixture constants in I `lumio_local_context.py` can also go:
`P1_LOOKUP_OKF_METRIC_PAGE`, `P1_DERIVED_OKF_METRIC_PAGE` and
`P1_UNUSED_OKF_METRIC_PAGE`. Parent whole-tree identifier search found only their
definitions. Keep deliberate live legacy decoys used to detect fallback.

## 2. Eleven precise whole-test consolidations

These are optional cleanup, not C6 completion gates. Keep the named counterpart
and transfer every listed unique assertion **before** removing the candidate.
No broad CLI/API/wheel/backend consolidation follows from this table.

| Candidate to absorb/remove | Keep | Evidence / mandatory transfer |
| --- | --- | --- |
| T `test_graph_traversal.py:96` — `test_outgoing_neighbors_within_authorized_set` | Same file `test_candidate_titles_none_means_all_loaded_titles_authorized` | Identical fixture, unmarked default-None call and `['Delta', 'Gamma']` result. Neither supplies an explicit authorized subset. Keep the actual subset/bridge/endpoint refusal tests. |
| L `test_remote_index_binding.py:92` — `test_adapter_with_no_index_anywhere_returns_empty` | `test_remote_index_location.py::test_none_index_returns_empty_not_fallback` | Same unbound adapter/no-index call; implementation returns before reading pages or storage. No unique assertion. Keep bound missing/stale/unhealthy fallback cases. |
| W `test_link_candidate_graph_impact.py:219` — `test_component_join_does_not_fire_when_already_connected` | Same file `test_fragile_strengthening_signal` | Same Alpha→Gamma→Beta fixture, candidate and ranker. Keeper also asserts no component join plus the stronger positive signal. No transfer. |
| W `test_documents_extra.py:127` — `TestRouting.test_docx_routes_to_anydoc` | `TestRouting.test_office_formats_route_to_anydoc` | Same effective `.docx` suffix/None-MIME route; selector uses suffix/MIME, not basename. Family already includes `.docx`. No transfer. |
| W `test_documents_extra.py:159` — `TestRouting.test_html_routes_to_markitdown` | `TestRouting.test_broad_formats_not_covered_by_anydoc_route_to_markitdown` | Same `.html`/None-MIME route; family includes it. No transfer. Real converter/error/provenance tests stay. |
| `tests/test_workspace_certification.py:131` — `test_workspace_lockfile_is_the_single_coordination_point` | `tests/test_workspace_layout.py::test_workspace_has_one_root_lockfile_and_disjoint_import_roots` | Same root lock existence and Wiki/LanceDB member-lock absence. Keeper additionally checks Workspace. No distinct fixture/mark or assertion. Do not describe it as checking Ariadne's member-lock absence. |
| A `test_git_authoring.py:956` — `test_review_bodies_arrive_in_bounded_parts` | Same file `test_review_parts_retrieve_every_artifacts_later_bodies` | Identical long native Policy and review seam. **Transfer first-part `complete is False`**; retain later-window, revision, inventory and exhausted-short-artifact assertions. |
| W `test_s3_publish.py:329` — `test_publish_advances_the_active_pointer_to_the_new_version` | Same file `test_first_publication_has_no_existing_pointer` | Both publish VALID/v1 to a fresh MemoryStore and only check the initial pointer. No second-version advance is exercised by the candidate. No transfer. |
| W `test_s3_publish.py:320` — `test_publish_records_sizes_that_match_the_materialized_bytes` | Same file `test_publish_writes_a_digest_and_fingerprint_manifest` | Same initial publication; keeper already checks bytes/size/digest. **Transfer persisted manifest JSON read-back via `_read_manifest`**; returned-record checks alone are not equivalent persistence proof. |
| W `test_cli_open_actions.py:218` — `test_explicit_published_version_replays_a_historical_version` | Same file `test_page_actions_pin_the_exact_resolved_published_version` | Candidate reads current v1, and its absent sentinel was never inserted. Keeper replays actual v2 content after pointer advances to v3 through the same CLI/Location seam. No unique assertion. |
| W `test_cli_open_actions.py:347` — `test_rendered_open_actions_never_contain_object_store_urls` | W `test_citation_actions.py::test_rendered_source_lines_are_never_signed_or_object_urls` | Parent-verified cross-area overlap: both directly call the same action builder/renderer with the same HTTPS source fixture; the CLI-named test does not call CLI. **Repair the keeper with actual object-store source URLs, retaining HTTPS label checks and exercising GS/Azure exclusions with real inputs.** Assert suppression of the `source-url` action, not a blanket prohibition on legitimate S3 CLI open commands. |

One additional **block**, not a whole numerical test, is redundant:
A `test_evals.py:478–490`, repeated ad-hoc `FANNED_SOURCE` refusal, is covered by
`test_define_metric_rejects_fanout_source`, which additionally guards compilation.
Remove only that repeated block/unused fixture dependency. Keep the renderer's
independent inflated 700/400 calculation, sanctioned 300/400 result and governed
fan-out refusal: they are different contracts.

**Rejected consolidation:** do not drop W
`test_s3_publish.py::test_rollback_target_validation_is_read_only` as an exact
duplicate of `test_rollback_activates_a_prior_complete_version_without_rewrites`.
The targets differ: one rolls back to VALID/flat content, the other to
CATEGORIZED content. Flat reading remains supported. Keep both input shapes
(or parameterize them without dropping a case) and repair byte-level oracles.
The surface reviewer's LS-05 merge recommendation is superseded by this parent
disposition; no third review or rerun is needed.

## 3. Four Activity Log tests: coordinate retirement with residual code/gates

ADR-0022 explicitly retires new Activity Log generation and append tests. In T
`test_kb_control.py`, these are obsolete generation requirements:

- `test_append_activity_log_creates_file_with_marker` (`:608`)
- `test_append_activity_log_appends_one_line_preserving_history` (`:622`)
- `test_activity_log_entry_is_grep_friendly` (`:646`)
- `test_activity_log_collapses_newlines_in_description` (`:659`)

Remove append/log-exists requirements only from
`test_publish_then_validate_categorized_kb_is_portable`; retain its other
portability/category/navigation/Entity assertions. The required
`products/lumio/scripts/verify_lumio_wiki_wheel.py:179–185` also still demands
new log generation.

**Hand back the coordinated cleanup, not a standalone gate deletion.** The
snapshot still exports/implements `append_activity_log_entry`. Align that
residual writer/export and verifier with the accepted ADR in separately
authorized work, or obtain an explicit owner decision superseding the ADR.
This audit grants neither product API removal nor a waived wheel gate.

Keep marked historical-log exclusion/fingerprint stability, unmarked/wrong-marker
collision refusals and no-generation assertions. If a portability fixture needs
an old log, author historical marked bytes; do not call the retired generator.

## 4. Repairs worth doing instead of deleting their tests

The following are the highest-value repair families. Expected outcomes derive
from written contracts, authored fixtures, hand-worked numbers or before/after
bytes—not from copying current implementation results. References in parentheses
identify the detailed reviewer findings retained with this report.

### R1. Restore the actual native prerequisite before interpreting downstream checks

**Keep + repair; migration-family observations, not fresh C6 fix obligations.**
Examples: A `test_git_admission.py::admit`, `test_context_admission.py::admit`,
`test_review.py::native_admission_args`, `test_cli.py::create_git_demo_project`,
`test_contracts.py::contract_project`, `test_s3_storage_access.py::s3_git_project`,
and `setup_wheel_walkthrough.py`. Many positive numerical/ODCS/MCP/Example
checks depend on them. Classic-only projects, missing native controls or plain
`--confirm` can refuse before those checks. Do not restore legacy execution or
weaken correct consent/source/Context guards to turn them green.

Also preserve, while repairing: current revision handoff in refresh tests;
real source/citation binding; actual failure-injection commit seams; valid
profile-versus-artifact budget predecessors; operation-appropriate support
revision; required Policy classification in I `lumio_s3_context.py::_bound_release`
and `lumio_local_context.py::t2_reference_candidate`; native Workspace S3 setup;
and complete required `sources` attribution in Workspace retrieval responses.
The S3 fixture's old `context_layer` write alone is **not** proof of failure:
its helper still creates that directory plus a native KB. The demonstrated
Policy-closure/setup defects are narrower.

Keep hand-worked 150/2, 60, 300/400, source A/B identities, integer fidelity,
exact admitted versions, unchanged historical bytes and no-SQL spies. Repair
shared setup once, then use only delta-relevant validation under a later grant.
(CN K1/K2/07/08; CR-01/02; BP-K1/K2; LS-06.)

### R2. Observe post-call bytes, not stale objects or file names

- A `test_git_authoring.py::test_unsupported_project_refuses_on_every_public_open_without_mutation`
  and its historical-admission counterpart compare path lists, not protected
  bytes. A `test_init.py::test_scaffold_refuses_a_retired_context_layer_project`
  only checks that old content still starts with frontmatter. Preserve these
  public entrypoint cases; reuse the existing byte-map/hash-manifest idiom.
- W `test_managed_ingest.py::test_managed_ingest_missing_source_id_blocks_the_write`
  reads the pre-call `kb.pages`; W `test_git_authoring.py::test_managed_ingest_refusals_preserve_author_files`
  reuses the first refusal's `after` map after the second refusal. Recapture
  actual files/manifest after each call, accounting for deliberate setup.
- W `test_s3_publish.py` rollback no-rewrite checks and the actual-endpoint
  rollback counterpart compare object keys, not contents. Capture target
  key→bytes/digests before and after. Retain flat/categorized and real-endpoint
  distinctions; same names can hide destructive overwrites.

These are real data-loss protections, not obsolete tests. (CN-03; LA-02; LS-05.)

### R3. Supply and assert the privacy witness actually claimed

- W `test_capture.py::test_quoted_json_credentials_are_redacted_before_capture_staging`
  supplies an escaped password but checks only the API-key marker and some
  `[REDACTED]`. Assert the authored password/recognizable suffix is absent
  from the persisted page as well. **No current product leak was established.**
- W `test_graph_exchange.py::test_export_graph_public_scope_never_leaks_restricted_or_internal`
  links to `secret.md`, but its hidden page is `secret_doc.md`, with a different
  title and no matching alias. Correct the target and establish a real edge
  in privileged export before checking public omission. Keep all existing
  node/title/summary/ID checks.
- Repair the retained renderer case in §2 with actual object-store source
  URL inputs. An HTTPS-only fixture cannot prove cloud-URI suppression.

These strengthen existing written privacy tests; they are not new speculative
security findings. (LA-01; GR-04; LS-12 and parent cross-area consolidation.)

### R4. Corrupt a valid current graph cache, not an already-invalid old encoding

W `test_graph_state.py::{test_inconsistent_edge_count_rejected,test_inconsistent_incoming_not_reverse_of_outgoing_rejected,test_stray_incoming_entry_rejected}`
uses two-field edges with the current nine-field schema version. Decoding
refuses before the named count/reverse checks. Reuse the existing v2 helpers,
establish a valid control and change only the intended consistency condition.
Keep separate wrong-version/arity tests. (GR-01.)

### R5. Successful enhanced retrieval must distinguish results from empty/fallback

L `test_remote_index_location.py::test_local_semantic_and_hybrid_through_location`
and `test_remote_lancedb_s3_compat.py::test_s3_compat_remote_semantic_build_search_and_identity`
accept any list, including `[]`. The remote lexical success check also accepts
zero-index fallback. Use known authored vector/page matches, nonempty expected
Evidence and appropriate semantic/fusion stages; reject `index-fallback` on
these healthy paths. Keep truthful fallback tests separately. Fake-encoder
wiring is not real semantic-quality evaluation. (GR-02.)

### R6. Eligibility needs a loaded, matching page that should be excluded

L `test_graph_tables.py::test_graph_retrieval_bounds_identical_across_zero_index_and_lancedb`
and `test_ontology_parity.py::test_identical_retrieval_eligibility_across_projections`
expand over their entire fixture corpus. Backend equality/all-title subset
checks cannot detect a missing nonempty prefilter. Strengthen one existing
parity scenario with an authored matching isolated decoy and an explicit
eligible set. Keep empty-set and topology/lifecycle checks. (GR-03.)

### R7. Use fixtures where the intended graph/ranking rule changes the answer

T `test_graph_traversal.py::test_results_stable_across_repeated_loads` writes
neither IDs nor Claims, then compares empty graphs. Reuse a valid persisted
Claim fixture and assert a known nonempty path across loads.
W `test_semantic_maintenance.py::test_page_selection_is_bounded_and_hub_first`
happens to choose the lexically first page even without hub ranking; give a
later-sorting page strictly greater accepted connectivity. The strongest-first
tests in `test_dream_duplicate_candidates.py` and `test_dream_synthesis_impact.py`
also align lexical order with signal strength. Author a stronger pair that
sorts later than a weaker pair; retain within-tier stable ties. (LS-01; GR-05/07.)

### R8. Remove tautological identity/serialization proof

W `test_graph_state.py::test_msgpack_artifact_not_published_or_disturbed`
compares the same post-regeneration fingerprint twice. Capture before the
actual regeneration and compare after; keep artifact bytes/no-msgpack writes.
T `test_kb_control.py::test_write_control_file_round_trips_and_is_deterministic`
reads the same overwritten path twice; read first bytes before the second write.
W `test_artifact_store.py::test_publication_writes_private_binding_manifest_before_activation`
has another `fingerprint_sources(root) == fingerprint_sources(root)` assertion.
Remove that assertion or use a real before/after operation with a narrowly
accurate claim; do not invent another private-state suite when existing tests
already cover the relevant state. Keep its valuable persisted binding/privacy
checks. (GR-06; LS-03; LA-05, parent-minimized response.)

### R9. Use the already-authored lookup count instead of `actual == actual`

A `test_mapping_inspection.py::test_the_three_families_report_honest_shape_evidence`
declares lookup `matched: 3`, but reads `matched_left` with actual value as its
fallback. The lookup match count is therefore never checked. Assert the
fixture's **3 of 6** matches explicitly; retain missing/ambiguous/mismatch and
multiplicity checks. Do not assert a fabricated count for a family without
an authored expectation. (CR-04.)

### R10. Put the competing `.env` in an actual ancestor

W `test_env_loader.py::test_discover_stops_at_trusted_project_root` puts the
unwanted `.env` in a sibling directory. Searching above the trusted root
would not find it. Move it to the actual parent and keep nearest/root-local
positive cases. This prevents accidentally selecting another project's KB.
(LS-02.)

### R11. Make the create-if-absent rollback predecessor actually absent

W `test_s3_publish.py::test_first_publication_via_rollback_is_create_if_absent`
first publishes v1, which creates the pointer. Delete only that fixture
pointer, assert absence, then roll back the complete target. Retain concurrent
CAS/stale-expectation cases separately. This tests recovery after pointer loss,
not another update of an existing pointer. (LS-04.)

### R12. Stop silently discarding the authored DOCX scenario

W `test_managed_ingest.py::test_managed_ingest_never_requires_the_documents_extra`
contains a `.docx`/None-MIME record but `continue`s over it. `ingest_into_worktree`
accepts optional MIME and filename-based routing. Exercise that existing
host-authored case; no converter should run. Preserve the independent
base-install/import-isolation and actual converter tests: this source test
alone is not an isolated no-extra-install proof. (LA-03.)

### R13. Keep operational/packaging checks, fix their oracle or launcher

- `verify_workspace_wheel.py`, `tests/test_workspace_layout.py` and
  `tests/test_workspace_certification.py` require obsolete SDK ranges/extras
  or reject valid two-component bounds. Compare with the **approved** native
  dependency/extra contract. Keep explicit allowed dependencies, forbidden
  imports, artifact provenance and actual installation checks; do not generate
  expectations from the same installed metadata being judged.
- W `test_wheel_isolation.py::test_console_script_reports_version` accepts any
  `lumio-wiki ` prefix. Compare the complete output with independent installed
  distribution metadata, not the module constant.
- W `test_wheel_isolation_documents.py::test_doctor_reports_documents_extra_installed`
  accepts `not installed`. Assert the affirmative status for that capability.
- A `test_docker_mcp.py::test_compose_external_project_auth_and_proposals_survive_recreation`
  resolves nonexistent package-root Compose files. Use the actual
  `products/ariadne/deploy/` files; preserve opt-in auth/mount/persistence checks.
- A `test_skill.py::test_skill_teaches_context_knowledge_and_typed_page_edits`
  still requires a retired `context_layer/references/...` operational path.
  Expect current native guidance while preserving its human/permission rules.

These are meaningful release/user-facing checks, not permission to delete
binding gates or run Docker/builds during this audit. (BP-1/2/3; CR-05/06.)

### R14. Narrow misleading parity/attestation claims instead of duplicating proof

W `test_llm_distiller.py::test_provider_driven_and_passthrough_extraction_share_the_same_shape`
compares explicit passthrough with default passthrough, not a provider. The
neighboring `test_provider_distilled_markdown_carries_routing_into_extraction`
already uses the real Distiller with fake external I/O. Fold useful unique
routing assertions there if redundant, or truthfully name a required default
contract. Do not create another provider journey just to satisfy the old title.

A `test_git_authoring.py::test_unchanged_computation_preserves_attestation_but_a_changed_one_cannot`
never starts with an earned attestation. Existing I
`lumio_local_context.py::test_integrated_technical_profiles_preserve_evidence_and_curated_content[changed-computation]`
does exercise preservation/invalidation from a real authored attester. Narrow
the older pending-only claim; do not add parallel earned-attestation coverage.
Keep distinct source-only and authored-evidence invalidation. (LA-04; CN-01.)

### R15. Do not infer a new computation ownership rule from an invalid fixture

A `test_git_proposals.py::test_system_owned_native_pages_are_refused[computations-page]`
uses `# c` without a canonical title. A bare `ValueError` can come from title
validation, not generated-content ownership. Keep meaningful index/log refusal
and generated trust/provenance protections, but reconcile authored versus
generated Computation semantics before asserting a path-wide prohibition.
An authored Computation is currently supported. The misleading assertion is
proven; a product ownership bypass or a new blanket ban is **unverified**.
Reuse existing valid native fixtures if the retained rule needs this case.
(CN-02.)

## 5. Explicitly keep these production safeguards

- Independently worked numerical totals, fan-out and grain refusal, NULL/time/
  Unicode/integer/byte bounds, mutable-source rechecks, sanctioned SQL/compiler
  controls and correct refusal-before-execution timing.
- Exact source approval/effective destination, separate caller data grants,
  credentials not echoed, visibility before ranking/counting, required Context
  and human composite admission. Optional/advisory knowledge stays distinct.
- Commit/review/published-version identity, immutable originals, stale consent,
  failure-before/after-activation, crash/retry recovery and real post-call bytes.
- Real CLI/MCP serialization and wire boundaries; Workspace/Pi client wrappers;
  fresh-process recovery; optional/base wheel independence and artifact identity.
- Supported standalone Lumio/Flat/OKF/history/exporter behavior, marked legacy
  exclusions and unsupported-input refusal. A `legacy` name alone is not debt.
- Model/provider fakes limited to external I/O, actual remote-store transport
  tests, and source-environment import blockers **alongside** installed wheels.
  They exercise different faults, not a redundant layer quota.

Do not delete tests just because they are small, use mocks, repeat a data
fixture, fail after migration, or look implementation-adjacent. Conversely, a
substring, list type, same-state comparison or two agreeing backends is not
independent proof of a richer production claim.

## 6. Disposition and safe next step

**Task:** audit all existing tests in the selected frozen C6 snapshot for
production relevance under agent-guardrails. **Result:** complete static file
review, explicit pruning/repair decisions, per-file inventory and evidence
limits. **Disposition: accept this audit; hand back implementation.**

A later cleanup grant should refresh these exact candidates against C6's
then-current result, omit already-repaired findings, keep unique assertions,
and run only checks justified by the actual cleanup delta. Existing project/CI
requirements still bind; no broad rerun or relaxed expectation follows from
this report. Activity Log API/gate reconciliation is separate from mechanical
pruning. No automatic commits, issue changes, integration, push or publication.

Security: **n/a for changes—this audit changes no product boundary.** Existing
privacy/security assertions were evaluated as production protections. Weak
regression oracles are not proof that a live product vulnerability exists.

Not checked: runtime passing/failing/skipped counts, timing/flakiness, real-model
quality, installed artifacts, live services/credentials, actual current CI,
private app, external projects, or newer C6 modifications. Production tracing
was targeted to judged tests/callers, not an exhaustive source-code audit.
No claim of complete behavioral coverage or production readiness is made.

## 7. Evidence provenance

Detailed complete reviewer reports are retained in the parent session artifact
directory:
`/home/volker/.pi/agent/sessions/--home-volker-coding-ariadne--/test-audit-20261112/`.
Their source ranges, authored oracles, known in-flight distinctions and limits
are evidence, not additional execution approvals. Parent dispositions in this
report override any broader/conditional deletion suggestion in those reports.
The initial launcher failures were resolved only after explicit owner approval
of a per-process PATH correction; no global configuration/install was changed.

| Complete report | SHA-256 |
| --- | --- |
| `boundaries-packaging-report.md` | `9fbbdd645d7d13feea6d7a245d71b6b15b5c9990de9ee4fcd4df8446a94fd39a` |
| `core-native-report.md` | `f81a40c826de5914ff3666a3db69fd836bcbe3e2823c378a5078451f762ff35b` |
| `core-runtime-report.md` | `137c1ed185b4baa30b489aa126d317f9aca1a4574250d11a99aa1550b03fd738` |
| `graph-retrieval-report.md` | `1d6f0d29a356d856bfe05d733690f3db857dffdd5e1b81badfa387177ebee368` |
| `lumio-authoring-report.md` | `c761b43122b4ce854f7dbbbb30d4055ec1bf264a9964f4215e70c1c8da570ed3` |
| `lumio-surface-report.md` | `c6a3ce8d717d5971fc2a4464f117ac16f0902409d212977c000ff5864bfd8b6a` |

## Appendix: complete assigned-file inventory

The table records static read coverage and a concise retained-job/disposition
excerpt from the responsible reviewer. `Full`/`Fully inspected` means the file
text and assertions were read, **not** that the test passed or every production
helper was audited. The specific parent decisions above override grouped KEEP
labels and the rejected LS-05 consolidation. Detailed source ranges remain in
the reports named in §7. Excerpts end with an ellipsis where shortened;
this is not a substitute for the exact parent dispositions above.

| File | Reviewer area | Retained job / disposition excerpt | Read |
| --- | --- | --- | --- |
| `integration/tests/conftest.py` | boundaries-packaging | KEEP helper: intentionally resolves paired Core test helpers without private application imports. Not a collected test. | Full (static) |
| `integration/tests/lumio_contribution_review.py` | core-native | KEEP whole staged-tree review of executable/knowledge/contract changes, explicit exclusion of unstaged/untracked bytes,… | Full (static) |
| `integration/tests/lumio_local_context.py` | core-native | KEEP independent 150/2, 175, 0/150 and projection oracles; complete multi-metric/input Context before live work; source-free… | Full (static) |
| `integration/tests/lumio_managed_sources.py` | core-native | KEEP actual CLI/Python composite consent, absolute private-profile identity, whole-baseline original retention,… | Full (static) |
| `integration/tests/lumio_metric_mvp.py` | boundaries-packaging | KEEP: independently seeded revenue 100+50, exact knowledge/policy citations, response limits, stale scope/build consent,… | Full (static) |
| `integration/tests/lumio_s3_context.py` | core-native | KEEP S3 effective publication binding, Core-last activation with real native residue, separate analytical grants, pinned A/B… | Full (static) |
| `integration/tests/workspace_data_sources.py` | core-native | KEEP Workspace additional grant plus exact native Source Approval, endpoint A/B distinction, credential-only rotation, correct… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/setup_wheel_walkthrough.py` | boundaries-packaging | KEEP+REPAIR BP-K1: CI-called installed CLI/scaffold/source approval/three-event governed result. It is not directly collected. | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_answer_examples.py` | core-native | KEEP native SQL provenance opt-in, source-free CLI/MCP save/search, explicit admission, distinct identities,… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_authoring.py` | core-native | KEEP operator-owned local/exact-object references, no fetch before approval, traversal/symlink refusals, stable byte-snapshot… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_authoring_mcp.py` | core-native | KEEP real stdio versus authenticated HTTP wiring, fixed project/role authority, no approval/admission tools, schema refresh… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_business_answers.py` | core-runtime | KEEP: wrong-population control, full row sets, final versus tool values, provenance/snapshot hashes, fail preservation,… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_cli.py` | core-runtime | KEEP + REPAIR CR-02: actual `cli.main` JSON/error and input-file/stdin contracts; temporal/decimal encoding,… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_context_admission.py` | core-native | KEEP no-model applicability, inherited semantic gates, assertion eligibility, explicit selection, hypothesis/counterevidence,… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_context_browsing.py` | core-native | KEEP + REPAIR native metadata directory, exact canonical body, unavailable/escaping paths (CN-04); retire classic/no-title… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_context_signals.py` | core-native | KEEP independently fixed instants, equivalent offsets, UTC date boundary, unknown naive/malformed/absent expiry, JSON evidence… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_contracts.py` | core-runtime | KEEP + REPAIR CR-02: immutable official schema/fixture pins, exact producer bytes and versions, supported scalar… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_data_signals.py` | core-runtime | KEEP: native public-release path, per-fact exact identities, directly cited evidence only, advisory… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_discovery.py` | core-runtime | KEEP + known helper repair: source-free startup across registrations, no mutable-draft/source reads, admitted context-only… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_docker_mcp.py` | core-runtime | KEEP + REPAIR CR-05: opt-in actual Compose/network bearer probes, deployment user/port/mount behavior and proposals surviving… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_evals.py` | core-runtime | KEEP + REPAIR CR-01; CONSOLIDATE only CR-07 block. Preserve hand-written SQL/golden arithmetic, ad-hoc USD/customer means and… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_git_admission.py` | core-native | KEEP exact consent/evidence/baseline, complete immutable snapshot, source identity, current-approval-before-open, session… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_git_authoring.py` | core-native | KEEP inherited whole-candidate validation, deterministic native computation, persistent repair budget, bounded review,… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_git_only.py` | core-native | KEEP ephemeral successful/refused ad-hoc execution, explicit authoring retention, admitted-only Example lifecycle/history,… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_git_proposals.py` | core-native | KEEP isolated proposals, stale/competing writes, exact staging, safe identities/credentials/trust, bounded committed reads,… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_git_source_access.py` | core-native | KEEP exact host-root source grant, decoy avoidance, current host document policy, changed registry/endpoint authorization,… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_ingest.py` | core-native | KEEP currently reachable optional converter routing, supported suffix set, real native/PDF/DOCX/HTML/RTF conversions with… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_init.py` | core-native | KEEP confirmed native empty setup, private namespace/profile, no-overwrite/nonempty/symlink protection, optional MCP and… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_mapping_inspection.py` | core-runtime | KEEP + REPAIR CR-04: all three families, exact scoped identities/leading zeros, types and permissions,… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_mcp2_compatibility.py` | core-runtime | KEEP + known admission repair: actual raw stdio JSON-RPC frames, Unicode/escaping/request-ID accounting, structured/generic… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_mcp_toolsets.py` | core-runtime | KEEP + known fixture/support-revision repair: real stdio registration/schema, prohibited human operations, no tool… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_multifact.py` | core-runtime | KEEP: independent fan-out, graph ownership/layout, target tuple audits and mutable-key rechecks, quoted identifiers, scoped… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_profiler.py` | core-runtime | KEEP: bounded sample facts without key inference, known columns/null/distribution statistics, qualified FK targets, real… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_query_containment.py` | core-runtime | KEEP: distinct nested IO-bypass shapes rejected before any caller-derived DuckDB call, canary nondisclosure/no persistence,… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_query_records.py` | core-runtime | KEEP: independent specification e1–e8 top-N/ties/repeats/NULLs, suffix, timestamp/fold/gap/malformed eligibility, RE2, helper… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_query_results.py` | core-runtime | KEEP + REPAIR CR-01/02: pretransfer bounds, full aggregate inputs, escaped cells, types, positional collisions/lookahead,… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_render.py` | core-runtime | KEEP: reachable compiler alias/dependency/cycle/time/error contracts plus executed independent 14/18 and chained-field… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_review.py` | core-native | KEEP noninteractive read-only display, inert mapping selection, one exact delegated admission, bounded presentation,… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_s3_lakehouse.py` | core-runtime | KEEP: real shared-builder Delta/Iceberg/DuckLake reads of two differently credentialed endpoints, independent 60/40 versus… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_s3_storage_access.py` | core-runtime | KEEP + known legacy-project/admission repair CR-02: actual signed route/secret setup errors, effective endpoint grants, stale… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_s3_storage_profiles.py` | core-runtime | KEEP: inert credential-free validation/identity, intersecting/similar scope boundaries, explicit named credentials, endpoint… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_seed.py` | core-runtime | KEEP: authored fixture determinism/idempotent logical content, designed gotchas and independent billable/currency SQL versus… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_serve.py` | core-runtime | KEEP numerical/SQL/parser/ephemeral/server boundaries; REPAIR native prerequisites CR-01; RETIRE only two obsolete fallback… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_setup.py` | core-runtime | KEEP: source-free/operator-only setup, noninteractive refusal to infer approval, exact digest handoff, idempotent proposals,… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_skill.py` | core-runtime | KEEP install/reinstall/status/user-content/symlink/no-data-loss and packaged policy guidance; REPAIR CR-06.… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_sources.py` | core-runtime | KEEP registry/path/credential/refusal, planned statements and actual SQLite/file/Delta/native catalog reads, read-only… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_sources_remote.py` | core-runtime | KEEP: real local HTTP range transport for remote native catalog plus separately read backing Parquet, absent catalog/backing… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_spreadsheet_import.py` | core-runtime | KEEP: independently handwritten OOXML, deliberately cached 7 not recalculated 30, exact 37 sum, sheet/cell/row provenance,… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_status.py` | core-runtime | KEEP + known admission-helper repair: truthful metadata-only readiness, none/invalid/context-only states, pinned digest/source… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_terms.py` | core-native | KEEP exact aliases versus case-sensitive physical identity, ambiguity/concept alternatives, no substring/SQL/join inference,… | Full (static) |
| `products/ariadne/packages/ariadne-data/tests/test_validate.py` | core-native | KEEP compile-only versus live applicability, explicit source-free CLI, malformed model capture, independent 700/1100… | Full (static) |
| `products/lumio/clients/pi-workspace/disclosure-boundary.test.ts` | boundaries-packaging | KEEP: actual installed Pi sessions and extension, provider fetch capture, switch/resume/manual+automatic… | Full (static) |
| `products/lumio/clients/pi-workspace/tests/upload.test.ts` | boundaries-packaging | KEEP: production upload wrapper sends independently authored BOM/CRLF/invalid-UTF8 bytes and required headers through HTTP;… | Full (static) |
| `products/lumio/eval/conftest.py` | graph-retrieval | KEEP: committed corpus validation and gold-set loading; invalid fixtures cannot silently feed recall gates. | Full (static) |
| `products/lumio/eval/test_ontology_eval_gate.py` | graph-retrieval | KEEP: authored exact ontology expectations, deterministic reports, measured wrong expectations, explicit zero-row reporting,… | Full (static) |
| `products/lumio/eval/test_retrieval_eval_gate.py` | graph-retrieval | KEEP: real public retrieval ladder, positive recall threshold, graph degradation comparison, optional BM25/vector/hybrid… | Full (static) |
| `products/lumio/packages/lumio-lancedb/tests/test_graph_tables.py` | graph-retrieval | KEEP; GR-03 repair. Distinct persisted schema/metadata/lifecycle, accepted-edge parity, corrupt/stale/partial fallback,… | Full (static) |
| `products/lumio/packages/lumio-lancedb/tests/test_lancedb_adapter.py` | graph-retrieval | KEEP: **non-collected `main()`** is explicitly invoked from isolated-wheel CI; real build/search/citation/base-dependency… | Full (static) |
| `products/lumio/packages/lumio-lancedb/tests/test_ontology_parity.py` | graph-retrieval | KEEP; GR-03 repair. Same authored corpus over MessagePack/Lance tables, lifecycle/redirect/source metadata and topology… | Full (static) |
| `products/lumio/packages/lumio-lancedb/tests/test_publication_s3_compat.py` | graph-retrieval | KEEP: requested-index completion/manifest digest, failed build keeps pointer, remote graph stale/missing checks, rollback and… | Full (static) |
| `products/lumio/packages/lumio-lancedb/tests/test_remote_index_binding.py` | graph-retrieval | KEEP constructor-bound remote location/fingerprint and override cases; GR-C1 consolidates only the unbound/no-index duplicate. | Full (static) |
| `products/lumio/packages/lumio-lancedb/tests/test_remote_index_location.py` | graph-retrieval | KEEP; GR-02 repair and GR-C1 retained case. Typed-location coercion, sidecars, model mismatch, failed rebuild invalidation,… | Full (static) |
| `products/lumio/packages/lumio-lancedb/tests/test_remote_lancedb_s3_compat.py` | graph-retrieval | KEEP; GR-02 repair. Real named S3-compatible build/read/sidecar/model/graph transport remains necessary; MemoryStore is not… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_ariadne_context.py` | lumio-authoring | KEEP: exact local/S3 native admission, namespace/subtree/digest pins, immutable historical reads, full native metadata, typed… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_artifact_store.py` | lumio-authoring | KEEP + LA-05: independent source identities, corruption, hash/size bounds, recoverable retention saga, required… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_artifact_store_s3_compat.py` | lumio-authoring | KEEP: actual endpoint digest verification, exact signed GET/expiry, role policies, public-prefix privacy, CLI inspection/fetch… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_authoring_journey.py` | lumio-authoring | KEEP: full two-page cross-linked candidate + ontology, unchanged baseline binding reuse, default required retention, failure… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_authoring_review.py` | lumio-authoring | KEEP: real staged tree versus excluded work, commit hook drift, exact whole-tree checking, digest-bound readable review,… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_capture.py` | lumio-authoring | KEEP + LA-01: consent-first capture, transcript/source binding, independent redaction markers, raw-turn refusal, private… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_capture_adapters.py` | lumio-authoring | KEEP: synthetic-only Codex/Pi discovery, original byte export, duplicate native IDs, malformed histories, output preservation,… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_citation_actions.py` | graph-retrieval | KEEP: browser URL/path normalization, shell-safe copyable actions, exact resolved version, distinct external/private source… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_cli.py` | lumio-surface | KEEP command usage/exit codes, optional dependency guidance, eval routing, bounded/raw page metadata, graph recovery, setup… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_cli_open_actions.py` | lumio-surface | KEEP exact version/copyable-action replay, JSON identity and location, invalid browser base and source-label separation.… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_cli_remote_lance.py` | lumio-surface | KEEP backend/mode/config validation, optional-adapter guidance, fingerprint-bound fallback and truthful empty fallback, real… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_cli_remote_lance_s3_compat.py` | lumio-surface | KEEP real endpoint remote-index use, missing/stale index fallback and status JSON; this supplies actual backend I/O… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_cli_s3.py` | lumio-surface | KEEP credential-free URI/config boundaries, native Git review/confirm publication, receipt-failure retry after later rollback,… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_cli_setup_s3.py` | lumio-surface | KEEP configuration read-back, private store omission from tracked guidance, exported/project precedence, reader vs maintainer… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_cli_status.py` | lumio-surface | KEEP truthful validation/readiness/fallback/private-store-kind summaries and setup's post-write degraded status.… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_discovery_graph.py` | graph-retrieval | KEEP: deterministic link resolution/provenance, exclusions, incoming/path/depth, scopes, accepted-only Claims, stable IDs, no… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_documents_extra.py` | lumio-authoring | KEEP; optional LA-06 consolidation only: Office/PDF/HTML route, raw-byte hashes, real converter behavior, malformed/empty… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_dream_duplicate_candidates.py` | graph-retrieval | KEEP; GR-07 repair. Advisory identity suggestions, type/alias distinctions, bounded output, explicit-only merge,… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_dream_synthesis_impact.py` | graph-retrieval | KEEP; GR-07 repair. Accepted-only synthesis signals, no automatic mutation, bounded transitive depth and ID lookup,… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_entity_claims.py` | graph-retrieval | KEEP: aggregate parser/ontology errors, ID uniqueness, literal/domain/range/lifecycle/evidence rules, redirects, canonical… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_entity_merge.py` | graph-retrieval | KEEP: retained transformation semantics through native candidate/worktree operations, stable survivor, Claim… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_entity_resolution.py` | graph-retrieval | KEEP: exact ID/title/alias/redirect precedence, truthful ambiguity/unresolved/optional unavailability, CLI and read-only… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_env_loader.py` | lumio-surface | KEEP distinct parser, quoted/relative/URI values, nearest-file authority, process-env non-mutation and trusted-root semantics;… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_external_vault_import.py` | lumio-authoring | KEEP: generic external directory versus generic OKF policy, safe defaults, synthetic/provenance preservation, truthful dropped… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_git_authoring.py` | lumio-authoring | KEEP + LA-02: captured Git bytes, exact source A versus subsequently registered B, separate preview/confirm, stale… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_graph_exchange.py` | graph-retrieval | KEEP; GR-04 repair. JSON/GraphML semantics, foreign/malformed/colliding import diagnostics, reviewable stubs and native CLI… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_graph_retrieval.py` | graph-retrieval | KEEP: graph selection with actual excluded matching decoy, seed inclusion, depth/limit, empty seeds, accepted/disputed and… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_graph_state.py` | graph-retrieval | KEEP; GR-01/06 repairs. Current-cache integrity, rebuild/fingerprint/extractor identity, atomic replacement failure, no… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_graph_structural_diagnostics.py` | graph-retrieval | KEEP: hand-worked directed counts, WCC coverage, cycles, scope, bounded diagnostics and candidate filtering; not the same… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_ingest_journey.py` | lumio-authoring | KEEP: actual extraction/overlay/apply helpers still used by native worktree routes. Destination collisions, FIFO/socket… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_ingest_journey_isolation.py` | lumio-authoring | KEEP: embedded child drives real model-free Git ingestion/publication while blocking optional imports. This is… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_journey_setup.py` | lumio-surface | KEEP real Git read-only probes, truthful push/PR-unverified, profile confirmation/non-mutation/containment, source-baseline… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_journey_setup_creation.py` | lumio-surface | KEEP creation preview/digest/confirm, no-write refusals, native Git ownership, skill/profile byte drift, partial-I/O residue… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_legacy_proposal_export.py` | lumio-authoring | KEEP: spec0008 §7 explicitly retains this operator-selected migration reader. Inventory/preview non-mutation, unadmitted… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_link_candidate_graph_impact.py` | graph-retrieval | KEEP; GR-C2 consolidates exact duplicate only. Advisory structural ranking, stable ties, immutable outputs, explicit discovery… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_link_candidates.py` | graph-retrieval | KEEP: deterministic plain/alias mention finder, ambiguity/word boundaries, linked/code masking and exact location/snippet… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_llm_distiller.py` | lumio-authoring | KEEP + LA-04: real optional Distiller interface, actionable missing-extra errors, retries/exhaustion/auth refusal, configured… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_location_snapshot.py` | graph-retrieval | KEEP: public filesystem Snapshot wrapper versus loader behavior, retained captured fingerprint, immutable collection surface,… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_maintenance.py` | lumio-surface | KEEP read-only lint/dream, checked Git link application, source provenance retention, advisory drift/coverage tiers and… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_managed_ingest.py` | lumio-authoring | KEEP + LA-02/03: source/page contract, original identity/hash reuse, retained additional sources, private raw exclusion and… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_mcp_server.py` | lumio-authoring | KEEP: exact eight-tool read-only contract, fresh bound Snapshot, real server registration, startup refusal, result projection,… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_okf.py` | lumio-surface | KEEP public portable Profile1/Profile2 interchange; RETIRE excluded private-app alias test LS-08. Generic OKF remains… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_page_removal.py` | graph-retrieval | KEEP: real native removal candidate/worktree, dependent Claim/link/pin repair, preservation of external/image/code/ambiguous… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_plan04_agent_workflows.py` | lumio-authoring | KEEP: CLI canonical read/bounds, safe machine errors, copyable actions tied to the original KB, ontology-aware prompt, real… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_private_profile.py` | lumio-authoring | KEEP: explicit operation-scoped selection, namespace/path/duplicate-key refusals, safe inspection, exclusive configuration,… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_qa_validation_report.py` | lumio-surface | KEEP aggregated public diagnostics and scoped orphan/link/stale/contradiction outcomes plus focused forwarding edge cases.… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_remote_derived_index.py` | lumio-surface | KEEP descriptor identity/version/store/fingerprint mapping and no backend dependency in the neutral module.… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_retrieval_eval.py` | graph-retrieval | KEEP: hand-worked recall math, dedup, negative/passage/citation measurement semantics, authored gold parsing, third-party… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_review_after.py` | lumio-surface | KEEP valid/absent/malformed date semantics, exact inclusive due boundary, advisory-only validation/lint/dream/status; YAML… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_s3_agent_journey_s3_compat.py` | lumio-surface | KEEP fresh-process setup→mixed original ingest→Git admission→reader→exact historical original→retry/rollback journey.… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_s3_compat.py` | lumio-surface | KEEP real client read/corruption/snapshot isolation vs filesystem parity. Its immutable-version case only compares distinct… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_s3_location.py` | lumio-surface | KEEP wire corruption/digest/size/path confinement, filesystem equivalence, snapshot pinning, optional-extra errors and no-disk… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_s3_publish.py` | lumio-surface | KEEP shared transport kernel integrity, CAS races/ETag fail-closed, snapshot isolation, derived completion/retention hook… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_s3_publish_s3_compat.py` | lumio-surface | KEEP real conditional-write/rollback/cleanup endpoint boundary, separately from native CLI admission. REPAIR byte inventory… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_s3_version_diff.py` | lumio-surface | KEEP no-change, additions/changes, title/lifecycle/visibility/source transitions, reserved/non-Markdown exclusion, parser… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_s3_version_diff_cli.py` | lumio-surface | KEEP validated historical accessor, human/JSON diff output and missing-version exit. CLI validates/serializes selected… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_search_json.py` | graph-retrieval | KEEP: numeric accounting with authored match counts, graph trace composition, public CLI JSON/human consistency and… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_semantic_maintenance.py` | graph-retrieval | KEEP; GR-05 repair. Fake external provider but real parser/edit composition, inspected-set/field/lifecycle rejection,… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_skill_management.py` | lumio-authoring | KEEP: missing/stale/corrupt status, journaled atomic update/restore, concurrent fallback serialization, safe target selection,… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_skill_public_surface.py` | lumio-authoring | KEEP as **documentation contract guards**: packaged public-API guidance, citation/refusal, private originals not Evidence.… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_source_baseline.py` | lumio-authoring | KEEP: exact-revision metadata-only bootstrap, no forged availability, additive history, unchanged retained metadata, strict… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_source_exchange_s3_compat.py` | lumio-authoring | KEEP: completion-last/create-only objects, interrupted/lost-response recovery, kind/digest/size verification, no-clobber… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_source_handoff.py` | lumio-authoring | KEEP: exact contribution-range transfer, shared bytes without identity merge, convergent interrupted import, supplementary… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_source_inspection.py` | lumio-authoring | KEEP: exact version/Entity disambiguation, no latest substitution, malformed bindings, safe output names, verified… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_source_lifecycle.py` | lumio-authoring | KEEP: private registry state/reload atomicity, interprocess writers, safe IDs/diagnostics, retired-source refusal and lock… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_source_resolution.py` | lumio-authoring | KEEP: deterministic ambiguity rather than guessing, bounded candidates/suggestions, partly registered compound sources and… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_url_ingest.py` | lumio-authoring | KEEP: real fetch policy/wire path, private destination refusal, redirect/byte/header deadline, truthful final URL, native… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_wheel_isolation.py` | boundaries-packaging | KEEP+REPAIR BP-2: real console entrypoints, packaged skill/protocol, setup distinction, native ingest/publication,… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_wheel_isolation_documents.py` | boundaries-packaging | KEEP+REPAIR BP-3: extra resolution, import independence, real PDF text conversion and diagnostic. The conversion test's… | Full (static) |
| `products/lumio/packages/lumio-wiki/tests/test_wheel_isolation_llm.py` | boundaries-packaging | KEEP: optional provider install, honest base refusal, real `OpenAIDistiller` with fake completion I/O, CLI-created native page… | Full (static) |
| `products/lumio/packages/lumio-workspace/scripts/verify_workspace_wheel.py` | boundaries-packaging | KEEP+REPAIR BP-1: source/archive/installation binding, templates, base-vs-analytics boundary and console shipping. Explicit… | Full (static) |
| `products/lumio/packages/lumio-workspace/tests/test_workspace_analytics.py` | boundaries-packaging | KEEP: exact source and separate caller grants before access/conversion; real selected-source profiles and hand-worked revenue… | Full (static) |
| `products/lumio/packages/lumio-workspace/tests/test_workspace_enrichment.py` | boundaries-packaging | KEEP: accepted vs disputed claims, unchanged readers while pending/rejected, bounded selection/claim changes, exact retry… | Full (static) |
| `products/lumio/packages/lumio-workspace/tests/test_workspace_identity.py` | boundaries-packaging | KEEP: genuinely signed Entra claims, token/client/audience rejection, current membership, published reads, key rollover with… | Full (static) |
| `products/lumio/packages/lumio-workspace/tests/test_workspace_intake.py` | boundaries-packaging | KEEP: browser-only setup, no implicit adoption, exact bytes/retry conflicts, pending invisibility, current owner attachment,… | Full (static) |
| `products/lumio/packages/lumio-workspace/tests/test_workspace_local_auth.py` | boundaries-packaging | KEEP: actual CLI credential lifecycle including historical leading-minus credential IDs, purpose separation,… | Full (static) |
| `products/lumio/packages/lumio-workspace/tests/test_workspace_operations.py` | boundaries-packaging | KEEP: unmocked backup/restore over real S3 adapter with only transport construction replaced by MemoryStore; remote-byte loss,… | Full (static) |
| `products/lumio/packages/lumio-workspace/tests/test_workspace_recovery.py` | boundaries-packaging | KEEP: new interpreter reconstructs task state from persistence, does not replay approval, preserves A while B is current,… | Full (static) |
| `products/lumio/packages/lumio-workspace/tests/test_workspace_retrieval.py` | boundaries-packaging | KEEP+REPAIR BP-K2: fixture-authored sections/line spans, visibility before ranking/counts, exact historical reads,… | Full (static) |
| `products/lumio/packages/lumio-workspace/tests/test_workspace_review.py` | boundaries-packaging | KEEP: current independent browser review, entire effective continuation content, separate person/one-person exception, one-use… | Full (static) |
| `products/lumio/scripts/verify_lumio_wiki_wheel.py` | boundaries-packaging | KEEP: actual candidate/installed/source member identity, artifact roots, dependency/import absence, native Git… | Full (static) |
| `products/lumio/tests/test_core_sdk_index.py` | lumio-surface | KEEP public lookups, citation-bearing adapter-slot retrieval and actual LanceDB rebuild/freshness. Legacy flat pages… | Full (static) |
| `products/lumio/tests/test_graph_traversal.py` | lumio-surface | KEEP independently authored cyclic/parallel-edge graph, directions, bounded traversal and explicit authorized-subset refusals;… | Full (static) |
| `products/lumio/tests/test_health_report.py` | lumio-surface | KEEP health classification for stale index, missing summary, dangling Claim, unknown predicate, duplicate alias and invalid… | Full (static) |
| `products/lumio/tests/test_kb_control.py` | lumio-surface | KEEP v2 controls, category/pin declarations/refusals, canonical fingerprint changes, navigation/hot generation, reserved… | Full (static) |
| `products/lumio/tests/test_mykg_experiment_converter.py` | lumio-surface | KEEP existing experiment converter mapping/privacy/collision/unreviewed-edge/provenance constraints and CLI output. Caller… | Full (static) |
| `products/lumio/tests/test_okf_consumer_tolerance.py` | lumio-surface | KEEP foreign producer metadata loss disclosure, safe defaults, broken prose link preservation and export behavior. This is… | Full (static) |
| `products/lumio/tests/test_onboarding_journey.py` | lumio-surface | KEEP documented public CLI progression, local no-original honesty and script wrapper that CI uses against real S3. Source is… | Full (static) |
| `products/lumio/tests/test_registry.py` | lumio-surface | KEEP public registry field projection/counts and zero-index freshness/rebuild behavior. Zero-index vs explicit LanceDB adapter… | Full (static) |
| `products/lumio/tests/test_relationship_types.py` | lumio-surface | KEEP obsolete input **refusal** (including empty old relationships block), valid/unknown native predicate validation and… | Full (static) |
| `products/lumio/tests/test_release_policy.py` | lumio-surface | KEEP lockstep/range and release credential/gate/artifact structure checks. Notes-topic check targets historical v0.2.0… | Full (static) |
| `products/lumio/tests/test_setup_from_git.py` | lumio-surface | KEEP actual file:// clone, missing-tool/failure cleanup, invalid KB and argv/no-shell boundary, plus S3 transport refusal… | Full (static) |
| `products/lumio/tests/test_source_processor.py` | lumio-surface | KEEP text/Markdown bytes, independent source SHA-256 and authored section coordinates; genuine malformed UTF-8; injected… | Full (static) |
| `products/lumio/tests/test_wheel_verifier.py` | boundaries-packaging | KEEP: authored synthetic archives test production verifier enumeration for native extensions, relocated purelib/platlib, and… | Full (static) |
| `products/lumio/tests/test_zero_index_retrieval.py` | lumio-surface | KEEP no-adapter citations/trace, unknown/semantic refusal, nested/fenced passage coordinates, captured raw/identity metadata… | Full (static) |
| `tests/test_workspace_certification.py` | boundaries-packaging | KEEP+REPAIR BP-1; CONSOLIDATE only BP-4's function. Project manifests, extras, actual archives and bounded metadata check… | Full (static) |
| `tests/test_workspace_layout.py` | boundaries-packaging | KEEP+REPAIR BP-1. Root non-distribution, explicit members, single lock and disjoint namespaces implement written coordination… | Full (static) |
