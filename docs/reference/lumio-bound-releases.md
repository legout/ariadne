# Lumio bound releases reference

Ariadne projects can optionally bind a Lumio knowledge base as the source of
governed context. This page is the reference for that integrated route: what
the binding requires, what it admits, and what it refuses. The integration is
delivered against a strict local subset — everything not listed as supported
below refuses. Projects without the integration keep the standalone behavior
documented in the other references; nothing here adds a requirement for them.

## The integrated selector

An integrated project carries `context_integration.yaml` at its root:

```yaml
version: 1
mode: integrated
subtree: knowledge
namespace: urn:example:retail
profile: ariadne-context/1
```

The selector names version 1, integrated mode, the `knowledge/` subtree, the
expected KB namespace and the `ariadne-context/1` profile. It carries portable
selectors only — never credentials, private registry locations, publication
destinations, active pointers or a human-approval flag.

- Absence of the selector keeps the existing standalone route.
- A malformed or unsupported selector refuses; it never downgrades to
  standalone.
- An existing integrated runtime cannot be downgraded by a query or tool
  argument.

## One shared Content Commit

The Ariadne project is the Git worktree root; the Lumio Knowledge Base is its
`knowledge/` subtree. One exact jointly reviewed Git commit covers both input
scopes: a page-only edit cannot skip inherited OSI, ODCS, source or evidence
checks. Core-generated technical pages stay Core-owned; curated knowledge has
one maintained source in the KB. There is no bidirectional synchronization and
no independently editable mirror in `context_layer/`.

Git is the standard transport for both repositories. **Sync never activates a
release:** pulling, merging or checking out a branch — including the commit an
admission was previewed against — never changes what is served. Only the
explicit overall admission below activates a Bound Release, and a served
manifest is never mutated; a changed build or support set requires fresh
validation and a new matching admission.

`ariadne status` makes the distinction visible offline: it reports the local
HEAD of the checkout separately from the verified admission, whose Bound
Release digest, exact Published Version and declared supported operations are
disclosed from the verified admission descriptor only — never from the
working tree, and with no destination or source data. The operator flow for a
local fast-forward plus the ordinary reconcile/validate/review/confirm chain
is in [the local Git how-to](../how-to/lumio-git-local.md).

## Supported and refused operations

The delivered integrated contract (also stated in every Bound Release
manifest):

| Area | Delivered behavior |
| --- | --- |
| Storage | Local immutable Published Versions only. An S3 destination or reader refuses explicitly; mutable/current/latest reads and plain directories refuse. |
| Profiles | `metric`, `policy` and `reference` only, checked across the entire captured KB. A `reference` profile is supported ONLY as a fully validated structured Reference (spec 0010 contract, real Core inspection receipts for asserted mappings, exact human mapping confirmation). Any other Ariadne profile kind anywhere in the KB refuses admission — even when no metric references it. Ordinary unprofiled pages stay KB content and are never exposed as Core-validated technical references. |
| `get_metric` | Governed calculation with one exact Context Binding and the complete required Policy Closure, resolved in the same pinned snapshot before SQL. |
| `query_metrics` | Multiple predefined metrics over the admitted multi-fact graph, complete per-metric Policy context, exact citations. |
| `discover`, `list_metrics` | Source-free disclosure of the admitted catalog, binding identity and available/unavailable operations. No source is opened. |
| `list_datasets` | Retains its approved live-catalog semantics — it is not source-free. |
| `list_context_pages`, `read_context_page`, `search_context` | Source-free navigation over the pinned, operator-scoped published pages (see below). |
| `resolve_term` | Source-free terminology resolution over the pinned release's validated structured References (spec 0010 §6 semantics through the one shared resolver): exact field bindings, claim/confirmation status, AS-OF evidence freshness, version-qualified citations. No transform, no SQL rewrite, no join authority; an authored evidence value is disclosure, never authority. |
| Refused integrated operations | `query_detail`, `query_records`, `define_metric`, `save_example`, `search_examples` refuse as unsupported before planning or SQL — never a legacy-context fallback. The same callables keep working in standalone projects. |

A fully validated structured Reference (spec0029 §1.5) is the one supported
exception: its declared representations/mappings and the Core-attached
`ariadne_evidence` summary slot ARE the Reference contract. Measured authority
uses authentic Core inspection receipts; source-backed manual assertions keep
their native eligibility, an authored evidence value never authenticates
itself, and confirmation remains the exact native human selection. Every other
unsupported technical application field (physical-reference/identifier-mapping
extensions, SDK computation/executor/attester annotations) cannot be smuggled
into a supported kind; it refuses rather than being silently ignored.

## Overall admission

Activation is an operator-only overall preview and confirmation on top of the
existing human admission boundaries. No Agent role or MCP tool receives it.

1. One final Content Commit is captured and validated (native and joint checks
   run against those exact bytes; Source Approval precedes any live check).
2. The overall preview shows the exact composite review: Core candidate, Lumio
   publication review, both expected active states, effective scope, execution
   identities and the joint manifest — with every automatic native side effect
   named before confirmation.
3. One explicit human confirmation authorizes exactly that displayed composite.
   A changed fact or expired validation requires a new matching review.
4. Native publication and Core preparation complete and are verified;
   immutable artifacts are persisted before activation.
5. The extended Core admission descriptor (`.ariadne/current.json`) is written
   last and atomically with the Bound Release manifest and its knowledge pin.

A failure before activation leaves the previous integrated descriptor serving
its previous complete binding (or none, on first admission). A completed
standalone Lumio publication may remain after failed overall activation — that
residue was a disclosed part of the confirmed operation, but it is not an
active integrated release. Rollback is another explicit reviewed activation,
not a permission grant or history rewrite.

## The Bound Release manifest

The Bound Release is the immutable binding produced by overall admission. Its
credential-free manifest records the manifest version, the
`ariadne-context/1` profile, the explicit consumer operation support, the
content full commit and joint input digests; the admitted Core artifact,
source, ODCS and OSI identities; the KB namespace, immutable Published
Version, canonical fingerprint and the separate publication-manifest and
Source Reference Manifest digests; metric-to-Entity bindings with complete
required Policy identities; exact native validation/review references; the
exact Ariadne and Lumio build identities plus resolved compiler/execution
dependencies; and the effective Visibility Scope. Before an integrated read,
Core verifies the manifest digest and cross-checks all of these against the
verified admission. Missing, malformed or mixed fields refuse — a
self-consistent Lumio pin cannot authorize a different Core revision.

**Build and source matching.** Package version and import path alone are
insufficient: editable code can change in a tree without changing either. The
manifest binds actual relevant build/content identities. An admission obtained
with one build does not silently serve through another; incompatible or
unmatched identities require explicit revalidation and a new matching
admission. The publication-manifest digest and the Source Reference Manifest
digest are separate identities, and neither is the Bound Release's own digest.

## Visibility Scope

Visibility Scope is operator-authorized, project/release-bound, and defaults
to the explicit set `{public}`. Authored content cannot expand it; query
inputs, tool arguments and model prompts cannot select another scope. There is
no implicit public/internal/restricted hierarchy. Scope applies before lookup,
search, listing, citation assembly and output: every required Policy must be
readable in the same scope, and an invisible dependency is not skipped.
Diagnostics never leak a hidden page's content, title or topology. Native
private Source Registries and raw artifacts stay outside Git, release records
and query output.

## Source-free navigation

`search_context` (CLI `ariadne search-context`), and the
`list_context_pages` / `read_context_page` MCP and Agent tools, navigate only
the session's pinned Bound Release under the operator-authorized scope. They
never read `context_layer/`, a mutable checkout, an unpinned or unscoped SDK
snapshot, or a moving current pointer. Ranking is native Lumio lexical search.
Results carry the Bound Release digest, SDK namespace, Entity ID, Published
Version and exact page/passage citations; ordinary unprofiled pages appear as
documentation, never as Core-validated References. Missing advisory metadata
stays unknown rather than inventing verification or freshness. Hidden and
missing paths have the same scope-safe unavailable result. There are no
dedicated `list-context-pages`/`read-context-page` CLI commands — navigation
outside tools goes through `search-context` and the pinned release's pages.

## SDK pairing

The Lumio SDK is an optional dependency of the integrated route: a standalone
Core install never imports or requires it, and an integrated admission
requires an installed SDK build that actually provides the bound operations —
an older SDK refuses admission instead of being advertised with capabilities
it lacks. Public package version strings alone do not qualify a source for
these capabilities: the exact candidate wheel pairing (Core and producer
source refs and wheel digests) is recorded with the qualification run
evidence, not assumed from published versions.

### Release 0.6.0 / 0.4.0

The public pairing is `ariadne-data==0.6.0` with
`lumio-wiki==0.4.0` (Python >=3.14). Install the exact pair:

```sh
pip install 'ariadne-data[mcp]==0.6.0' 'lumio-wiki==0.4.0'
```

Omit `[mcp]` for CLI-only use; `lumio-lancedb==0.4.0` is an optional retrieval
adapter, not a Core requirement. Base Core still imports without either SDK
or MCP. Qualification records the exact producer source commit and each built
wheel hash. A different installed build needs genuine validation and a fresh
overall admission; it never upgrades an old Bound Release in place.
