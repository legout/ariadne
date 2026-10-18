# Changelog

## Unreleased

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
  download only the two public wheels during release promotion.
- Use environment-scoped TestPyPI/PyPI tokens, retain build provenance and byte
  checks, and preserve manual production approval.

See [release notes](docs/release-notes/v0.2.0.md) for migration, extras, Python
requirements and verification limits. The private application and joint Ariadne
context profile are outside this release.
