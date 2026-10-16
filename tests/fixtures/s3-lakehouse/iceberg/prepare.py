"""Regenerate the committed file-based Iceberg fixtures under this directory.

Run from the repository root with the dev environment::

    uv run --python 3.14 --extra dev python \
        tests/fixtures/s3-lakehouse/iceberg/prepare.py

Everything is prepared OFFLINE (no S3 endpoint is contacted): DuckDB's own
Iceberg writer produces the data parquet (the only component whose column
field-id metadata the reader needs), and the metadata json plus both Avro
manifest files are hand-assembled from the independently specified oracle
rows (see ``tests/s3_fixture.py``: storage A — 3 rows, sum 60, EMEA 40;
storage B — 2 rows, sum 200) with ``s3://`` locations pointing at the fixed
disjoint bucket/prefix scopes. Expected totals therefore derive from the
oracle inputs, never from reading Ariadne's output.

The Avro object-container encoding (zigzag varints, header map, one data
block, sync markers) is implemented below with the standard library only —
no new runtime dependency. See README.md in this directory for the fixture
schema and the exact role each file plays.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — dev environment

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:  # the oracle rows live in the shared S3 fixture
    sys.path.insert(0, str(REPO_ROOT))

from tests.s3_fixture import ORACLE_A_ROWS, ORACLE_B_ROWS  # noqa: E402

VARIANTS = {
    "retail": ("s3://retail/iceberg/orders", ORACLE_A_ROWS),
    "analytics": ("s3://analytics/iceberg/metrics", ORACLE_B_ROWS),
}
SNAPSHOT_ID = 918273645  # arbitrary fixed snapshot id, part of the fixture bytes


# ------------------------------------------------------------- avro encoding


def _zigzag(n: int) -> bytes:
    n = (n << 1) ^ (n >> 63) if n < 0 else n << 1
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _str(value: str) -> bytes:
    raw = value.encode()
    return _zigzag(len(raw)) + raw


def _bytes(value: bytes) -> bytes:
    return _zigzag(len(value)) + value


def _avro_file(schema: dict, row: bytes, sync: bytes) -> bytes:
    header = bytearray(b"Obj\x01")
    header += _zigzag(1) + _str("avro.schema") + _bytes(json.dumps(schema).encode())
    header += _zigzag(0)  # end of the header metadata map
    header += sync
    return bytes(header) + _zigzag(1) + _zigzag(len(row)) + row + sync


def _map_field(name: str, field_id: int, key_id: int, value_id: int, value_type: str) -> dict:
    """One optional Iceberg map field, Avro-encoded as the array-of-records
    ``logicalType: map`` layout real Iceberg writers use."""
    return {
        "name": name,
        "type": [
            "null",
            {
                "type": "array",
                "logicalType": "map",
                "items": {
                    "type": "record",
                    "name": f"k{key_id}_v{value_id}",
                    "fields": [
                        {"name": "key", "type": "int", "field-id": key_id},
                        {"name": "value", "type": value_type, "field-id": value_id},
                    ],
                },
            },
        ],
        "field-id": field_id,
    }


MANIFEST_LIST_SCHEMA = {
    "type": "record",
    "name": "manifest_file",
    "fields": [
        {"name": "manifest_path", "type": "string", "field-id": 500},
        {"name": "manifest_length", "type": "long", "field-id": 501},
        {"name": "partition_spec_id", "type": "int", "field-id": 502},
        {"name": "content", "type": "int", "field-id": 517},
        {"name": "sequence_number", "type": "long", "field-id": 515},
        {"name": "min_sequence_number", "type": "long", "field-id": 516},
        {"name": "added_snapshot_id", "type": "long", "field-id": 503},
        {"name": "added_files_count", "type": "int", "field-id": 504},
        {"name": "existing_files_count", "type": "int", "field-id": 505},
        {"name": "deleted_files_count", "type": "int", "field-id": 506},
        {"name": "added_rows_count", "type": "long", "field-id": 512},
        {"name": "existing_rows_count", "type": "long", "field-id": 513},
        {"name": "deleted_rows_count", "type": "long", "field-id": 514},
        {
            "name": "partitions",
            "type": [
                "null",
                {
                    "type": "array",
                    "element-id": 508,
                    "items": {
                        "type": "record",
                        "name": "r508",
                        "fields": [
                            {"name": "contains_null", "type": "boolean", "field-id": 509},
                            {"name": "contains_nan", "type": ["null", "boolean"], "field-id": 518},
                            {"name": "lower_bound", "type": ["null", "bytes"], "field-id": 510},
                            {"name": "upper_bound", "type": ["null", "bytes"], "field-id": 511},
                        ],
                    },
                },
            ],
            "field-id": 507,
        },
    ],
}

MANIFEST_SCHEMA = {
    "type": "record",
    "name": "manifest_entry",
    "fields": [
        {"name": "status", "type": "int", "field-id": 0},
        {"name": "snapshot_id", "type": ["null", "long"], "field-id": 1},
        {"name": "sequence_number", "type": ["null", "long"], "field-id": 3},
        {"name": "file_sequence_number", "type": ["null", "long"], "field-id": 4},
        {
            "name": "data_file",
            "type": {
                "type": "record",
                "name": "data_file",
                "fields": [
                    {"name": "content", "type": "int", "field-id": 134},
                    {"name": "file_path", "type": "string", "field-id": 100},
                    {"name": "file_format", "type": "string", "field-id": 101},
                    # the unpartitioned "void" partition struct: zero fields,
                    # zero encoded bytes
                    {
                        "name": "partition",
                        "type": {"type": "record", "name": "partition", "fields": []},
                        "field-id": 102,
                    },
                    {"name": "record_count", "type": "long", "field-id": 103},
                    {"name": "file_size_in_bytes", "type": "long", "field-id": 104},
                    _map_field("lower_bounds", 125, 126, 127, "bytes"),
                    _map_field("upper_bounds", 128, 129, 130, "bytes"),
                    _map_field("null_value_counts", 110, 121, 122, "long"),
                    {
                        "name": "equality_ids",
                        "type": ["null", {"type": "array", "element-id": 136, "items": "int"}],
                        "field-id": 135,
                    },
                ],
            },
            "field-id": 2,
        },
    ],
}


def manifest_bytes(data_path: str, record_count: int, file_size: int) -> bytes:
    """One ADDED DATA entry with every optional statistic map null."""
    row = bytearray()
    row += _zigzag(1)  # status: ADDED
    row += b"\x00" * 3  # snapshot_id / sequence_number / file_sequence_number -> null
    row += _zigzag(0)  # content: DATA
    row += _str(data_path)
    row += _str("parquet")
    row += _zigzag(record_count)
    row += _zigzag(file_size)
    row += b"\x00" * 4  # lower/upper bounds, null counts, equality ids -> null
    return _avro_file(MANIFEST_SCHEMA, bytes(row), b"S" * 16)


def manifest_list_bytes(manifest_path: str, manifest_length: int, added_rows: int) -> bytes:
    row = bytearray()
    row += _str(manifest_path)
    row += _zigzag(manifest_length)
    row += _zigzag(0)  # partition_spec_id
    row += _zigzag(0)  # content: DATA manifest
    row += _zigzag(0)  # sequence_number
    row += _zigzag(0)  # min_sequence_number
    row += _zigzag(SNAPSHOT_ID)
    row += _zigzag(1)  # added_files_count
    row += _zigzag(0)  # existing_files_count
    row += _zigzag(0)  # deleted_files_count
    row += _zigzag(added_rows)
    row += _zigzag(0)
    row += _zigzag(0)
    row += b"\x00"  # partitions -> null
    return _avro_file(MANIFEST_LIST_SCHEMA, bytes(row), b"L" * 16)


def metadata_document(location: str, rows: int) -> str:
    return json.dumps(
        {
            "format-version": 2,
            "table-uuid": "7d5c0e88-64d4-4ccf-8a3b-1c2c5a9e5b11",
            "location": location,
            "last-sequence-number": 0,
            "last-updated-ms": 1792000000000,
            "last-column-id": 3,
            "schemas": [
                {
                    "type": "struct",
                    "schema-id": 0,
                    "fields": [
                        {"id": 1, "name": "id", "required": False, "type": "int"},
                        {"id": 2, "name": "amount", "required": False, "type": "int"},
                        {"id": 3, "name": "region", "required": False, "type": "string"},
                    ],
                }
            ],
            "current-schema-id": 0,
            "partition-specs": [{"spec-id": 0, "fields": []}],
            "default-spec-id": 0,
            "last-partition-id": 0,
            "default-sort-order-id": 0,
            "sort-orders": [],
            "properties": {},
            "current-snapshot-id": SNAPSHOT_ID,
            "snapshots": [
                {
                    "snapshot-id": SNAPSHOT_ID,
                    "sequence-number": 0,
                    "timestamp-ms": 1792000000000,
                    "manifest-list": f"{location}/metadata/manifest-list.avro",
                    "summary": {
                        "operation": "append",
                        "total-records": str(rows),
                        "added-records": str(rows),
                        "total-data-files": "1",
                        "added-data-files": "1",
                        "total-delete-files": "0",
                        "deleted-records": "0",
                        "deleted-data-files": "0",
                        "total-position-deletes": "0",
                    },
                    "schema-id": 0,
                }
            ],
            "snapshot-log": [],
            "metadata-log": [],
        },
        indent=2,
    )


def prepare(variant: str, location: str, rows: list[tuple], workspace: Path) -> None:
    """Write one committed fixture variant; ``workspace`` is a scratch dir."""
    scratch = workspace / variant
    con = duckdb.connect()
    con.execute("LOAD iceberg")
    values = ", ".join(str(row) for row in rows)
    con.execute(
        # nosemgrep — fixture-authored literal oracle rows; COPY takes no binds
        f"COPY (SELECT * FROM (VALUES {values}) t(id, amount, region)) "
        f"TO '{scratch}' (FORMAT ICEBERG)"
    )
    con.close()
    data = next((scratch / "data").glob("*.parquet")).read_bytes()

    target = Path(__file__).resolve().parent / variant
    (target / "metadata").mkdir(parents=True, exist_ok=True)
    (target / "data").mkdir(parents=True, exist_ok=True)
    (target / "data" / "data.parquet").write_bytes(data)
    manifest = manifest_bytes(f"{location}/data/data.parquet", len(rows), len(data))
    (target / "metadata" / "manifest.avro").write_bytes(manifest)
    snap = manifest_list_bytes(f"{location}/metadata/manifest.avro", len(manifest), len(rows))
    (target / "metadata" / "manifest-list.avro").write_bytes(snap)
    (target / "metadata" / "v1.metadata.json").write_text(metadata_document(location, len(rows)))
    (target / "metadata" / "version-hint.text").write_text("1")
    print(f"prepared {variant}: {len(rows)} rows, data parquet {len(data)} bytes")


def main() -> None:
    workspace = Path(__file__).resolve().parent / ".prepare-scratch"
    workspace.mkdir(exist_ok=True)
    for variant, (location, rows) in VARIANTS.items():
        prepare(variant, location, rows, workspace)
    print("fixtures written; commit the two variant directories, not the scratch dir")


if __name__ == "__main__":
    main()
