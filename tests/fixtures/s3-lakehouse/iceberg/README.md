# S3 Lakehouse test fixtures: file-based Iceberg

Committed, independently prepared Iceberg table fixtures for
`tests/test_s3_lakehouse.py` (issue #72/S2, spec 0025 §7 AC8). Each variant
directory mirrors the exact object layout the test uploads to its loopback
S3-compatible endpoint:

```text
retail/                       → s3://retail/iceberg/orders      (storage A)
analytics/                    → s3://analytics/iceberg/metrics  (storage B)
  metadata/v1.metadata.json   Iceberg v2 table metadata (schema, snapshot)
  metadata/manifest-list.avro the snapshot's manifest list (one DATA manifest)
  metadata/manifest.avro      one ADDED data-file entry (parquet, unpartitioned)
  metadata/version-hint.text  "1" — the reader locates v1 without guessing
  data/data.parquet           the single data file (3 rows A / 2 rows B)
```

## Schema and expected data

Both variants share one table shape — `id int (field-id 1)`,
`amount int (field-id 2)`, `region string (field-id 3)`, format-version 2,
unpartitioned, one snapshot (`918273645`), one data file.

Expected totals are the independently specified oracle inputs from
`tests/s3_fixture.py`, never observed implementation output:

| variant | rows | `SUM(amount)` | EMEA sum |
| --- | --- | --- | --- |
| `retail` | 3 | 60 | 40 |
| `analytics` | 2 | 200 | — |

The snapshot ids, UUID, timestamps, row counts and `file_size_in_bytes` are
fixed properties of the committed bytes; the manifest's size and count must
match `data/data.parquet` exactly.

## Preparation

`prepare.py` regenerates these files offline (no S3 endpoint contacted):

```sh
uv run --python 3.12 --extra dev python \
  tests/fixtures/s3-lakehouse/iceberg/prepare.py
```

DuckDB's own Iceberg writer (`COPY … TO … (FORMAT ICEBERG)`) produces the
data parquet — the one component whose embedded column field-id metadata the
reader requires — while `v1.metadata.json` and both Avro manifest files are
hand-assembled from the oracle rows with a standard-library Avro
object-container writer (zigzag varints, header map, one data block). The
`s3://` locations are the fixed disjoint bucket/prefix scopes; the endpoint
itself is supplied at test time by the storage profile, never by these files.

Producing runtime: DuckDB 1.5.6 with the repository `iceberg` extension
(`890b78a9c`). Regenerating under a different DuckDB may change the data
parquet bytes; re-run `prepare.py` and re-commit both variants together so
manifest sizes stay exact.
