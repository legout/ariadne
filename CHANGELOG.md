# Changelog

## Unreleased

## 0.3.0 - 2026-10-19

- Add the versioned Ariadne Context Profile and immutable context SDK: captured
  Metric/Policy/Reference annotations, explicit typed dependencies, exact
  Namespace/Entity identities, visibility-scoped reading and source-qualified
  citations. The producer preserves metadata without granting Core SQL/join or
  evidence authority; Ariadne's local MVP accepts only its supported subset.
- Capture the versioned `ariadne_context.ontology_catalog` from `lumio.yaml`
  during native candidate validation/publication, including managed destinations.
  Bind schema/catalog and exact source, subtree and publication identities; no
  caller-supplied empty-catalog pass or mutable-reader fallback.
- Release the two public foundation packages together at 0.3.0. The adapter
  requires `lumio-wiki>=0.3.0,<0.4.0`; runtime and package versions agree.
- Remove the manual deployment approval for future PyPI releases; candidate
  verification, tag restrictions and environment-scoped credentials remain.
- The base SDK stays model-free and independent of Ariadne, DuckDB and SQLGlot.
  The private application and Ariadne's deferred full integration are not part
  of this release. See [release notes](docs/release-notes/v0.3.0.md).

## 0.2.0 - 2026-10-18

### Breaking changes

- Replace persisted Ingest Proposals with ordinary Git-native authoring and
  separately confirmed exact-revision publication.
- Retire live proposal queue APIs; retain read-only legacy inventory and explicit
  export into unadmitted Git branches.
- Release `lumio-wiki` and `lumio-lancedb` together at 0.2.0. The adapter now
  requires `lumio-wiki>=0.2.0,<0.3.0`.

### Changed

- Bind source inspection and publication to exact Entity/Source versions, preserve
  private observations and history, and require explicit lifecycle/alias choices.
- Keep base reading portable, model-free and independent of Git and Ariadne.
- Verify index-installed wheel bytes without requiring optional origin metadata;
  check the two built public wheels before publication.
- Publish directly to PyPI using one environment-scoped token, retain build
  provenance and byte checks, and preserve manual production approval.

See [release notes](docs/release-notes/v0.2.0.md) for migration, extras, Python
requirements and verification limits. The private application and joint Ariadne
context profile are outside this release.
