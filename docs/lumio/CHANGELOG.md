# Changelog

## Unreleased

## 0.4.0 - 2026-10-21

- Add visibility-scoped navigation over admitted, version-pinned local Published
  Versions: list metadata, read exact canonical pages and search ordinary plus
  profiled pages through the existing native ranking engine.
- Preserve verbatim canonical search evidence, including escaped YAML metadata,
  multiline values and CRLF separators, with inclusive line coordinates.
  Filter scope before selection, ranking, counts, excerpts and citations.
- Keep the three navigation APIs local-only: S3, plain directories and moving
  pointers refuse. The existing typed profile reader retains its local/S3 contract.
- Document the optional Ariadne integration and the paired Core 0.6.0 local
  workflow. Producer annotations never grant source access, SQL, joins,
  Core inspection evidence or admission authority.
- Release `lumio-wiki` and `lumio-lancedb` together at 0.4.0; the adapter requires
  `lumio-wiki>=0.4.0,<0.5.0`. Python remains >=3.14, optional extras are unchanged,
  and the private application is excluded. See [release notes](release-notes/v0.4.0.md).

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
  of this release. See [release notes](release-notes/v0.3.0.md).

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

See [release notes](release-notes/v0.2.0.md) for migration, extras, Python
requirements and verification limits. The private application and joint Ariadne
context profile are outside this release.
