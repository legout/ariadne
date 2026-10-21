# Product-area layout implementation — 0031

Status: execution decomposition of approved spec0031 revision1. Owner: “Ok. Setze das um.”
Mode: supervised isolated candidate. No integration, push, rename, release,
tracker writes or cleanup of other worktrees/private data. This decomposition
adds no feature scope. Source: [spec0031](../specs/2026-10-21-0031-product-oriented-layout.md)
and [ADR0027](../adr/0027-public-monorepo.md). Baseline: bb11ee81; design eabcd9e.

Capture: no new domain vocabulary; accepted product-area ADR; spec acceptance
1–7 is authoritative; no unresolved material design choices. Existing record IDs
remain scoped, shared records stay root. Planning Contract1, installed revision unknown.

## Ownership and sequence

One Pi writer owns the entire isolated migration because moves, imports, workflow
paths and active maps share contracts. BB on the verified current host; worker
zai/glm-5.3/high, reviewer openai-codex/gpt-6.1-sol/high (owner's persistent
role preference, catalog verified). No nested delegation or shared memory writes.
Parent owns validation/environment setup, disposition and final review/acceptance.

This is a wide mechanical refactor: intermediate commits stay on the isolated
branch; only the assembled candidate promises green. No duplicate compatibility
trees: map tracked files once, repair callers, then check stale live references.

- [ ] L0: worker read-only preflight and precise move/caller/config inventory.
  Consume approved spec; return actual placement/runtime and concrete required
  path repairs. No tests, moves, installs or new artifacts in the checkout.
- [ ] L1: relocate tracked content by spec §3, classify shared vs product records,
  preserve blobs where no caller/link changes are needed; repair source/config/
  docs/example/fixture/Agent relative references and active ownership maps.
  Owned surface: tracked repository paths required by that mapping, root/scoped
  configuration and all real callers of changed paths. No runtime behavior/API,
  public identities, requirements, third-party lock resolution or package versions
  change. Preserve unpublished user files and ignored outputs. Inspect imported
  historical sources rather than bulk replacing their original record text.
- [ ] L2: root coordination-only configuration, product-native configuration,
  test namespace/import repairs, CI/release job path repairs retaining exact
  selections and published producer pin; document three explicit development
  profiles and fresh-clone commands. Existing two paired modules move together
  to integration/tests; shared helpers/fixtures have one canonical owner.
  Commit coherent L1/L2 candidate and create only authorized frozen result ref.
- [ ] L3: parent verifies artifact/source correspondence, executes existing checks
  below once on final assembled tree, dispositions failures before any repair.
- [ ] L4: one independent candidate review covering spec1–7 and integration
  effects, one bounded authorized fix pass and affected delta recheck if needed.
  Preserve frozen refs and raw failed outputs. Hand back isolated candidate;
  stop before target integration.

## One validation unit: path and packaging preservation

Obligation existing-check/no-new-test; named failures: lost/miscollected tests,
wrong repo roots or docs cwd, changed build contents/licenses, invisible optional
dependency leakage, wrong release artifact selection, unintended lock upgrades.
Independent oracle: approved destination map, baseline tracked blobs/manifests/
lock package records, existing native assertions and installed wheel walkthrough.
No new mirrored layout tests; adapt existing path/selection assertions only.

Parent inspects exact final commands after L0/L2 because new config paths own
discovery. Global budget: one execution of each applicable existing CI gate on
assembled candidate, not per commit/layer; stop the affected lane on failure.
No automatic retry, weakened assertions, new skip/xfail or borrowed test budget.

Required existing gates carried from ci.yml/publish.yml/release.yml:
- uv lock --check; uv sync --locked; native Ruff for Core and Lumio, shared
  lint separately scoped by final configuration. Third-party package record
  comparison must show no resolution changes.
- Lumio native full suite including its eval/member tests, -n4 never -nauto;
  shared workspace certification separately if removed from product default.
- Core native full selection: same three prepared-S3 exclusions, all default
  native tests and both explicitly named integration modules, fresh same-commit
  Core+SDK wheel environment without adapter; use real relocated paths.
- Existing isolated SDK wheel verifier, MCP entry/search smoke and adapter wheel
  certification; Core-only installed walkthrough outside source checkout with
  explicit SDK/MCP absence. Reuse these existing harnesses, no new wheel matrix.
- Existing onboarding/S3-compatible CI selection retained at new paths. Before
  execution, verify an owned disposable CI-pinned SeaweedFS4.45 can use the
  existing runtime and synthetic credentials only; otherwise report blocker
  rather than a skipped/empty pass. No unrelated retained service reuse.
- Static YAML/TOML parse, old/new tracked-file correspondence, current owned-link
  and executable-command cwd audit, stale live path search and diff inspection.

Unchanged numerical/admission semantics reuse their previous evidence except
where required native gates already exercise them. No additional numerical replay,
Agent/Tau setup, production access, hosted CI dispatch or tag workflow execution.

One pass is evidence only for its exact code/tests/environment. Relevant repair
invalidates affected evidence; parent authorizes only necessary recheck. No
extra ledger: existing run.json records refs, raw gate paths and dispositions.
