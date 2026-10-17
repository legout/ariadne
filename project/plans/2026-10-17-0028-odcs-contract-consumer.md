# Implementation plan: ODCS contract consumer

**Status:** approved revision 1, planning only. Owner, Pi conversation 2026-10-17, selected “Plan freigeben (Recommended)” without an execution start, then requested creation of C1/C2 tickets after the proposed publication of the approved planning documents. Only planning-document commits/push and tracker preparation are authorized by that follow-up; no worker, dependency installation, application test, implementation commit, feature integration or release is authorized. Isolated execution/source-freeze authority remains a separate prerequisite.

**Goal/source:** implement [specification 0028 revision 2](../specs/2026-10-17-0028-odcs-contract-consumer.md), not all ODCS semantics or shared #76 integration. Owner approval: Pi conversation 2026-10-17, “Schriftliche Fassung freigeben (Recommended)” for written r1, then “Live-Katalog erhalten (Recommended)” for r2's scoped correction. Spec sections own formats, checks and outcomes; this file owns sequencing and verification only.

## Readiness, ownership and constraints

- Code baseline is main `84004210cce4e3efcc2a9ccc73067e05aa8018f1`; the subsequent planning-only publication changes no application code. The approved specification/ADR/glossary and this plan are published for stable tracker references. Before any writer, freeze the exact approved source, current canonical ticket bodies and plan in an isolated execution base and record their identities in normal orchestrator state. Do not treat the code baseline as containing the new specification, include unrelated main files or infer implementation/publication authority from ticket creation. Execution approval must cover the isolated source freeze and candidate commits; without it, stop at planning.
- Capture: four glossary concepts and the Authoring Proposal extension are recorded in `CONTEXT.md`; [ADR-0025](../adr/0025-odcs-producer-contracts-and-local-bindings.md) owns producer/consumer separation; spec 0027 has the scoped extension notice. The owner settled the version, dialect, profile, binding, evidence and admission decisions. Shared #76 authority remains unselected and excluded.
- Default execution is **supervised**. Use `orchestrate-implementation` for host/role/model/thinking preflight, registered isolated worktree allocation under `${XDG_STATE_HOME:-$HOME/.local/state}/worktrees/`, source freeze, state and committed-result handoff. Resolve the actual current/configured Pi host; do not assume a historical Paseo identity or resurrect the removed issue73 v314 environment. No dispatch is authorized yet, and no model/host fallback is selected here.
- One sequential writer owns the two slices in one isolated registered candidate worktree. They share `authoring.py`, `validate.py`, snapshot/approval/discovery paths and guidance. Parallel writers would create avoidable interface/merge risk. After C1's high-risk boundary review passes, the same writer may continue C2; downstream work must not consume an unreviewed boundary.
- Python >=3.14, existing DuckDB/SQLGlot/OSI/OKF, optional MCP 2.2.0, plus the approved `jsonschema>=4.18` Core dependency. An explicitly authorized execution may prepare isolated declared dependencies and disposable synthetic Git/DuckDB fixtures. Prove the qualified interpreter imports this worktree's Core, not a released/noneditable copy. No global environment changes, live-model calls, private/production data, native PostgreSQL-quality engine or local tau-mcp installation is included.
- Preserve native Source Approval, effective S3 bindings, trusted native-DuckDB backing behavior, human admission, bounded repairs, existing metric/grain/numerical semantics and the new profile's limits. No contract-to-Policy conversion, inferred bindings/IDs, automated document rewriting, general SQL tool, new tool registration, legacy migration, shared ABI, version bump or release.
- The sole workflow is `orchestrate-implementation`; this plan adds no lifecycle or evidence ledger. Contract: planning-contract v1, installed provenance unknown.

## Coverage and integration order

| Slice | Approved source / criteria | Consumed and produced interfaces | Prerequisite |
| :--- | :--- | :--- | :--- |
| C1 — Native contract journey | Spec §§2–7, AC1–AC7 | Existing typed Git authoring, approved catalog selectors, SQL authority, deadline and validation/admission records → complete native contract/binding validation, scoped observations, gated admission and snapshot metadata | Approved plan/execution, frozen source and qualified isolated environment |
| C2 — Expose and package the native result | Spec §§2/7/8, AC1/AC7/AC8 | Reviewed C1 native results → existing CLI/MCP/Agent surfaces, user guidance and usable Core-wheel schema resource | C1 committed, focused evidence inspected and high-risk boundary review passed |

Each slice leaves the candidate coherent: C1 is usable through native Authoring/Discovery and static validation, not a parser-only foundation with an admission bypass. Its new typed kinds are routed through the existing Authoring CLI in C1. C2 finishes existing adapter descriptions/rendering and packaging qualification without creating another execution path. A required new behavior or ownership change returns to shaping rather than being hidden in C2.

## C1 — Complete native Git contract validation and admission

**Risk/unit V1:** high-risk external/declarative-input and public admission boundary; test obligation **`new-test`** for the uncovered contract behaviors below, with the three named existing checks supplying unchanged-caller regression evidence. One focused pytest selection after implementation, followed by immediate independent read-only boundary review before C2. Tests are new only for uncovered contract behaviors; existing native checks remain the oracle for unchanged project/source semantics.

**Files to create:**

- `src/ariadne/contracts.py`: source-free document/profile/binding validation and snapshot summaries; no connection or environment authority.
- `src/ariadne/authoring_contracts.py`: narrow typed artifact resolver, using the existing name/content/credential guards and revision-checked mutation seam.
- `src/ariadne/contract_inspection.py`: the bound approved-source observation/SQL execution seam, separated from pure loading because only this path may open sources.
- `src/ariadne/schemas/odcs/odcs-json-schema-v3.2.0.json` plus applicable upstream `LICENSE`/`NOTICE` resources; obtain from the approved exact commit, verify the spec's byte hash, retain attribution.
- `tests/test_contracts.py` and `tests/fixtures/contracts/` for the independently authored/official document inputs below. No generic fixture framework.

**Files to modify:** `pyproject.toml`, `uv.lock`; `src/ariadne/{proposals,authoring,authoring_cli,validate,admission,discovery,query}.py`; `sql_authority.py`/`execution.py` only for a minimal shared-helper change genuinely required by reuse. Do not rename broad `staging_dir` internals or change unrelated profiling/compiler behavior. Update affected existing assertions only where the new supported contract actually changes their expectation.

**Interfaces:** native contract and contract-bindings typed read/edit identities (existing revision and content receipts); spec §3's local binding format and exact native asset tuple; spec §§4–6's independent document/binding/check results; existing Core-owned validator identity/evidence/admission mechanisms. Default discovery is admitted-snapshot based. `discover` is offline; `list_datasets` still constructs the approved live catalog, and adds only snapshot metadata without extra inspection.

- [ ] Trace the allowed-path, initial-inventory, whole-snapshot, materialization, digest/recheck, review and admission consumers before extending scope. Include both contract extensions and the fixed bindings artifact everywhere; no arbitrary path editor, automatic Git initialization, inferred IDs or silent extension collision. Preserve exact submitted producer text rather than applying model normalization to it.
- [ ] Add the immutable packaged pin and Core dependency/lock. Implement deterministic structural validation and explicit version dispatch, scoped ID/internal-reference checks, binding resolution and supported-profile reporting. Preserve metadata; no remote schema/reference/variable/secret resolution. Keep document-valid versus valid-but-unsupported versus invalid binding distinct.
- [ ] Integrate static contract checks before `validate.validate`'s existing context-only early return as well as its model path. A malformed inherited contract must not disappear behind `not_applicable`. Static success never manufactures live proof; contract-free projects retain their previous applicable behavior.
- [ ] Resolve only explicitly bound approved assets/columns and verify their OSI source relationship. Reuse native source identity/frozen endpoint checks before opening a connection. Use targeted catalog reads, not `profile()` over the whole registry. Report missing observed tables/columns as drift and unavailable original physical types as unsupported.
- [ ] Implement the small field/SQL profile exactly from the spec, including required-NULL checks, individual scalar comparisons, open interval endpoints and result-shape/type refusal. Apply the existing SQL authority to the entire expanded/resolved tree, with relation scope limited to the selected asset; reject joins/foreign reads before execution. Reuse `execution.DeadlineBudget` and operator `project_inspection_limits`; do not add an independent engine, limit configuration or retry loop.
- [ ] Extend native validation evidence and its identity/version mechanism so pre-contract or weaker proof cannot attest the new gate. Bind final candidate, producer/binding dependencies, approved source/effective endpoint, pin/profile and real as-of scope; only complete applicable proof can satisfy the contracted-model admission gate. Include the existing stored-report reuse fast path: an expired or dependency-mismatched contract observation must not return as a reusable passing validation. Preserve original times when reusing valid observations. Unknown/unsupported requirements cannot be dropped through an incomplete property map, `severity`, custom metadata or forged authored proof.
- [ ] Add contract summaries to the pinned discovery view and native dataset entries. Recheck the managed snapshot as existing discovery does; never read candidate/current-worktree content as admitted. Missing/expired evidence remains explicit and triggers no background scan or new runtime refusal.
- [ ] Add the bounded focused verification below, commit the coherent native slice, and hand the exact result/evidence to the parent. Independent review covers the new parser/typed-path/dependency and source/SQL/evidence/admission boundary before C2 consumes it; it does not rerun green checks by default.

### V1: named failures, independent oracles and focused checks

Use one small `tests/test_contracts.py` file, not a test per module or complete ODCS feature matrix. The following named checks are its necessary scenarios; tightly related cases may be parameterized without mirroring the implementation:

| Check | Reachable failure / material impact | Independent expectation |
| :--- | :--- | :--- |
| `test_pinned_document_validation_is_offline_and_version_exact` | A rolling/wrong schema, older version label, ambiguous YAML or invalid reference is accepted as supported, or loading fetches data | Exact hash/version and research cases in spec §2/AC1; one official fixture with pinned provenance, schema-less four-field validity and scoped-ID/reference examples derived from the standard |
| `test_git_contract_journey_preserves_producer_and_requires_live_evidence` | New artifact bytes escape review/digests, static proof admits a dependent model, or scans rewrite producer intent | Spec §3/§6/AC2/AC6; a synthetic project, exact submitted bytes, native typed operations and human admission; no authored approval mock |
| `test_bound_schema_and_required_null_drift_are_explicit` | Missing/type-changed/NULL data passes, or unobservable physical type is treated as compatible | Spec §4/AC3 and an independently specified three-row DuckDB fixture: IDs 1/2/3, amounts 10/20/30, zero initial NULLs; change only the named column/type/value |
| `test_contract_source_and_sql_authority_precedes_execution` | A proposed server, unapproved binding or contract query reads outside its allowed asset/host boundary | Spec §4/§5/AC4/AC5; actual approved synthetic source for the valid path; a boundary spy is appropriate only to prove prohibited reads never start. Cover unavailable source separately from permission refusal, and one parameterized set of SQL out-of-profile inputs |
| `test_scalar_quality_obeys_pinned_comparison_and_result_semantics` | Wrong interval endpoints, bool/numeric coercion, NULL or multirow result gives false pass | Spec §5/AC5: hand-counted three rows; pinned docs explicitly define strict lower/upper bounds; NULL/cardinality rules come from the approved profile |
| `test_contract_evidence_dependency_and_age_gate` | Changed/expired/incomplete or authored proof admits a model or restamps historical measurements | Spec §6/AC6, fixed independently chosen observation times/dependency changes and existing human admission helper; unsupported requirements and tightened operator budgets cannot become passed evidence |

Only add a separate helper when used now. Reuse existing fixture builders where their declared source semantics fit DuckDB; do not silently patch SQLite fixtures into a different dialect or copy implementation-produced expected output. New-feature work has no separately assigned red-run campaign; bug reproductions/refactor pinning discovered later follow their own approved delta.

**One initial V1 command**, using the qualified absolute interpreter `$PY` in the candidate:

```sh
"$PY" -m pytest -q tests/test_contracts.py \
  tests/test_git_authoring.py::test_page_only_edit_validates_inherited_dependencies_and_exact_final_commit \
  tests/test_git_source_access.py::test_committed_registry_cannot_open_source_until_operator_approval \
  tests/test_git_admission.py::test_only_reviewed_validated_revision_activates_without_changing_candidate_bytes
```

The three existing nodes protect the real no-contract/inherited-revision/source-grant/admission callers touched by the shared integration. They are not a blanket rerun of every native suite. Prior #73/#74/0.4.1 evidence remains usable only for untouched behavior and matching inputs/environment, not as conformance proof for this new profile.

**Completion:** native static and approved-source paths implement AC1–AC6, produce pinned metadata for AC7, contract-free cases retain their contracts, focused evidence has actual exit status, and the immediate boundary review is pass. Any unresolved conflict or failed required gate stops C2.

## C2 — Existing adapters, guidance and packaged-resource proof

**Risk/unit V2:** normal integration risk at existing public adapters; test obligation **`existing-check`**, extending the two named existing discovery scenarios and using the artifact smoke below rather than creating another test framework. Packaging/docs are low risk but the new resource/dependency must actually work outside the source checkout. No second Core implementation or reopened settled boundary review.

**Owned files:** `src/ariadne/{cli,serve,authoring_cli}.py` where existing formatting/help/schema delivery needs updating; `src/ariadne/skill_assets/SKILL.md` and its affected existing references; `README.md`, new `docs/reference/data-contracts.md`, `docs/reference/data-sources.md`, `docs/reference/git-authoring-migration.md`; `tests/test_discovery.py`, `tests/test_mcp_toolsets.py` only for affected existing adapter cases. `ariadne-agent/{README.md,src/ariadne_agent/skills.py}` may receive mechanical guidance updates. Inspect `ariadne-agent/src/ariadne_agent/{analyst,authoring}.py` passthrough consumers; change runtime code only if the native contract cannot pass through unchanged, then stop for parent scope/budget disposition before adding an Agent lane or tau dependency. No public-tool growth.

- [ ] Preserve native JSON outcomes, role exclusions, revision selectors and actual queryable catalog fields. Render the contracts discovery group in existing human CLI output where needed; do not label `list_datasets` offline. Update typed-kind help/schema descriptions across existing authoring interfaces, not a new read/write/inspect command.
- [ ] Extend the existing `test_admitted_context_only_discovery_pins_snapshot_and_never_reads_sources` scenario with a valid unbound contract and the new group, inserting it through native authoring and producing new validation/review before human admission, not by reusing a pre-edit admission receipt. Its actual monkeypatched connection/network boundaries establish no source reads, including after the source disappears; preserve snapshot tamper refusal. Preserve/migrate only affected group assertions, never weaken the guard.
- [ ] Extend the existing native MCP source-free registration scenario if needed to prove the new group reaches the transport. Existing `test_mcp_toolsets.py::test_stdio_toolsets_share_core_and_exclude_human_operations` evidence may be reused when registration and wrapper code are unchanged; a changed serializer/role boundary requires a named focused check rather than claiming blanket transport proof. Agent passthrough inspection plus applicable unchanged evidence is not a live-model conversation claim.
- [ ] Document the exact schema pin, small profile, separate files, fixed identifiers/placeholders, required evidence, unsupported blocking cases, as-of limits and #76 boundary. Do not advertise full ODCS compliance or silently drop unsupported quality. No live access instructions execute during this task.
- [ ] Build only the Core candidate wheel once and verify the pinned resource and required dependency are in the artifact. In one disposable clean Python 3.14 environment, install that exact wheel with declared base dependencies (no MCP/documents/Agent), run one source-free `ariadne-validate` fixture from outside the repository with `PYTHONPATH` unset, and inspect the module/resource origin and actual validation result. This catches missing package-data or an accidental checkout-only resource lookup; no wheel matrix, Agent build or publication.
- [ ] Freeze the candidate and submit the C2 delta plus integration effects to one final read-only candidate review. Reuse C1's accepted findings/evidence; do not restart whole-candidate boundary review or rerun passing V1 for a handoff.

**One initial V2 pytest command:**

```sh
"$PY" -m pytest -q \
  tests/test_discovery.py::test_admitted_context_only_discovery_pins_snapshot_and_never_reads_sources \
  tests/test_discovery.py::test_mcp_discovery_starts_source_free_for_every_registration
```

The C1 lifecycle check also calls the actual live `list_datasets` route after admission and verifies r2: observed columns and ordinary approval refusal remain, and reading the contract annotation introduces no second contract inspection. No separate duplicate test is needed for that assertion. Do not duplicate the same proof at CLI, MCP and Agent layers; claim only exercised surfaces plus specifically justified unchanged passthrough evidence.

**Artifact smoke recipe** (absolute run-local paths `$DIST`, `$WHEEL`, `$SMOKE_ENV`, `$SMOKE_CWD`, `$SMOKE_FIXTURE` are allocated/recorded at authorized preflight, not guessed here):

```sh
uv build --wheel --out-dir "$DIST"
uv venv --python "$PY" "$SMOKE_ENV"
uv pip install --python "$SMOKE_ENV/bin/python" "$WHEEL"
(cd "$SMOKE_CWD" && env -u PYTHONPATH \
  "$SMOKE_ENV/bin/ariadne-validate" "$SMOKE_FIXTURE")
```

`$WHEEL` is the exact single newly built Core wheel. `$SMOKE_FIXTURE` contains an independent valid unbound v3.2.0 contract and no source/model declarations. Require exit 0 with only static scope, not a live-conformance claim. Inspect installed `ariadne.__file__`, `importlib.resources` schema bytes against the spec hash, and wheel dependency metadata; the origin must be the fresh environment, not the checkout. No smoke environment is created while this plan is merely proposed.

**Completion:** existing adapters/guidance match the reviewed native interface, the exact Core wheel can load and use its packaged pin offline, and final candidate integration review passes with qualification limits explicit.

## Bounded verification, review and handoff

- Planned budget for a separately authorized execution: the two initial focused pytest invocations above, plus **at most one parent-authorized narrow correction invocation** for the affected named failure (three pytest invocations maximum). A failure is not authority to broaden selection, install an alternate runtime, weaken an assertion or consume repeated rounds. Stop and ask when the budget or one-fix/one-delta-recheck boundary is reached. Do not repeat V1 after C2 unless a relevant production/test/input/environment delta invalidates it.
- The single Core build/base-wheel smoke is a separate assigned artifact check for the new packaged-schema failure, not a hidden suite. No Docker/S3/Lakehouse campaign, live model, whole Agent suite or full Core suite is assigned. Reuse relevant existing native S3/frozen-endpoint evidence because the approved scope changes no storage semantics; an actual storage-boundary delta returns to the parent.
- Written style remains binding: run targeted `ruff check` / `ruff format --check` on changed Python paths under the existing `pyproject.toml` settings, not unrelated repo-wide cleanup. Probe changed Python paths with active LSP diagnostics for unresolved names/call-signature/type integration defects; do not treat an empty cached result as a pass or sweep the whole workspace. Report pre-existing/environment-only diagnostics separately. No duplicate parent rerun when matching evidence already exists.
- The only existing repository workflow is `.github/workflows/publish.yml`, triggered by a separately authorized version tag. Its built-wheel Core suite and publication gates are unchanged; they do not authorize release or require an automatic release-qualification run for this supervised candidate. Surface future mandatory-gate conflicts rather than silently waiving them.
- Real callers are native typed Authoring/CLI, approved-source candidate validation, human admission, source-free discovery, live catalog listing and existing MCP/embedded-Agent wrappers. Incoming producer/agent-authored contract text and SQL are declarative external input; the host operator and their approved native DuckDB backing are not hostile by default. The concrete authority risk is contract input reaching validation before artifact admission and using a function/relation/endpoint to read private host files, credentials or an unapproved source. Apply the existing AST/source/credential boundaries; no malicious-admin, broken-TLS or generic hardening finding.
- Fresh reviewers receive the full current installed orchestrator/guardrails reviewer dispatch contract inline, approved spec r2/AC1–AC8, written Ruff/native-path/source/role rules, these actual callers and the precise delta. Reviewers report only findings and pass/fix-first; parent dispositions/authorizes fixes. At most one authorized repair pass and one delta-only recheck; unresolved/repeated blockers go to the owner, never a third round. Final review covers unreviewed C2 and integration effects, not settled C1 findings.
- Parent inspects actual final commit/tree/registered result refs, worktree status and evidence artifacts instead of trusting summary claims. Keep owner files, durable refs and existing workspaces. Report verified surface, unavailable tooling and remaining live-model/production/#76 limitations; choose accept/fix/hand back/ask. Stop before target integration, push, tracker closure, release or cleanup without separate authority.

**Handoff:** approved plan r1 against approved spec r2; planning-contract v1, installed provenance unknown. The later owner request authorizes publishing approved planning documents and creating linked tickets only, not execution. The next execution entry point is `orchestrate-implementation`, blocked on explicit supervised execution/source-freeze/dependency authority and its actual host/model/workspace preflight. No #75 implementation run exists; no feature integration or package publication is authorized.
