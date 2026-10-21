# Ariadne Context Profile — optional, pinned SDK consumption

The Lumio SDK can carry an optional, explicitly versioned **Ariadne Context
Profile**: native application metadata on ordinary Compiled Pages, captured
and validated against the versioned `ariadne_context.ontology_catalog`
declared in the Control File (`lumio.yaml`), and preserved unchanged through
Git authoring and Publication Admission. Pages without a profile are ordinary
KB content and stay fully functional.

This is an **optional integration**, not a feature of the base product:

- The base wheel depends only on `msgspec[yaml]` and `msgpack`. It never
  imports or requires Ariadne, DuckDB, SQLGlot, LanceDB or a model provider,
  and standalone Knowledge Base work is unaffected whether or not profiles
  exist. The isolated wheel verifier enforces this boundary.
- There is **no CLI command, service or background process** for the profile.
  Everything below is a Python library surface.

## Public surface and exact module paths

- `lumio_wiki.ariadne_context` — profile parsing/validation
  (`parse_ariadne_profile`, `validate_ariadne_profiles`, `policy_closure`),
  candidate inspection (`inspect_ariadne_candidate`, `disclose_native`), and
  the pinned published-context readers.
- `lumio_wiki.location.PublishedFilesystemLocation` — the pinned local
  published location used by navigation.
- `lumio_wiki` (package root) re-exports `open_published_context`,
  `ContextIdentity`, `ContextSnapshot`, `ContextBinding`, `ContextPageView`,
  `ARIADNE_PROFILE_VERSION` and the reader error types.

The SDK schema knows several native profile kinds; **Ariadne's consumer
validates only its supported Metric/Policy subset** and rejects any other
kind anywhere in the captured content. The consumer owns that check and the
overall admission — never the producer SDK.

## Exact identity and admission

Every reader opens **one exact admitted immutable Published Version**,
selected by a complete `ContextIdentity`: `namespace`, `profile_version`,
`published_version`, `fingerprint`, `publication_manifest_digest`,
`source_reference_digest`, `subtree` and the effective Visibility `scope`
(default `("public",)`). A fingerprint alone is not sufficient. Every
component is compared before any usable view; a changed or wrong version
refuses with `IdentityMismatchError`-family errors — there is **no fallback
to latest** and floating revisions (`main`, `head`, `current`, …) are never
valid pins.

`open_published_context` accepts an admitted **pinned local or S3 Published
Version** (S3 additionally requires the producer-side `metadata_store` used
at publication). It returns a `ContextSnapshot` of immutable
`ContextPageView`s plus `ContextBinding`s, where each metric view carries its
complete required Policy closure resolved through explicit typed Entity
references — never aliases, provenance Sources or navigation.

## Scoped local navigation (three operations)

```python
from lumio_wiki.ariadne_context import (
    list_published_context_pages,     # metadata-only, sorted by exact path
    read_published_context_page,      # one complete canonical page by path
    search_published_context_pages,   # native lexical search, visible set
)
```

These navigation operations are **local only**: the location must be an
explicitly pinned `PublishedFilesystemLocation`. Plain directories, moving
or current pointers, and **S3 navigation refuse explicitly** with the
reader's existing error categories before any store access. Each operation:

- applies the authorized Visibility Scope **before** path selection,
  ranking, snippets, excerpts, counts and citations;
- reuses the native reader's verification (manifest, fingerprint,
  source-reference, subtree, namespace/profile, completed admission);
- reuses the native `page_search` ranking engine — there is no second
  ranking implementation and no mandatory LanceDB;
- returns frozen immutable records: list results carry metadata only (profile
  kind or explicit `unprofiled`; no page body); a full page carries the exact
  canonical UTF-8 content, parsed body with body-start line, immutable
  native profile metadata (empty when unprofiled) and public provenance; a
  search hit adds the native score, matched fields/terms, snippet,
  visible-only completeness counts and a separately labeled verbatim excerpt
  with inclusive 1-based canonical line coordinates and section;
- gives missing and out-of-scope paths the **same scope-safe unavailability**
  (`UnadmittedInputError`), never disclosing a hidden title, Entity ID, text
  or topology.

## Boundaries

The profile is **metadata**. It does not authorize physical references,
joins, SQL, source access or numerical evidence. Lumio owns the curated
content and the exact knowledge identity — not executable OSI, database
observations, Source Approval, measurement authentication or numerical
governance. Readers never return a raw or unscoped snapshot, a mutable
`CompiledPage`, or anything from the private Source Registry; no private
artifact is fetched. An ordinary documentation page is **not** a
Core-validated technical Reference.

## Consumer pairing and activation

The integrated pairing is explicit and joint: the producer publication and
the consumer admission share one reviewable content commit, and Ariadne's
overall admission descriptor — granted by one explicit overall human
confirmation — is the sole integrated activation authority. A completed
Lumio publication can remain after failed overall activation and must not be
misreported as an active integrated release. Git/local sync is the normal
operator path; **syncing a checkout never activates anything**.

## Honest version statements

The published `lumio-wiki` release notes describe each release at its own
point in time. A public version number alone — including `0.3.0` — does not
establish that a given checkout, wheel or environment carries the surfaces
described here, and it never establishes an integrated consumer pairing.
Bind consumption to exact candidate identities: the source commit and the
exact wheel hash you actually install. Changed code or build identity
requires fresh validation and matching readmission; never relabel an old
admission as a new build.

## Public pairing

The release pair is `lumio-wiki==0.4.0` with `ariadne-data==0.6.0`.
The public-family adapter, when used, is `lumio-lancedb==0.4.0` and requires
`lumio-wiki>=0.4.0,<0.5.0`. See [0.4.0 notes](release-notes/v0.4.0.md).
Exact source/build identities remain required, and upgrading requires genuine
consumer validation and a new matching admission.
