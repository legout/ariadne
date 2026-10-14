"""Named S3 storage profiles × the existing Lakehouse readers (issue #72/S2,
spec 0025 §7 AC8): one REAL shared-builder connection per reader family
(Delta, file-based Iceberg, existing DuckLake) reading BOTH independently
credentialed loopback endpoints at once — storage A (retail): count 3,
sum 60, EMEA 40; storage B (analytics): count 2, sum 200.

Expected values come only from the independently prepared fixtures
(``tests/s3_fixture.py`` oracle rows; committed Iceberg bytes under
``tests/fixtures/s3-lakehouse/iceberg/``), never from observed
implementation output. Everything runs through the real shared builder
(``ariadne.sources.build_connection``) with the real ``delta``/``iceberg``/
``ducklake`` extensions — no mock connection ever substitutes. Required
capability is never skipped: a missing Docker runtime or extension blocks
the check (the test refuses rather than passing quietly). The actual
DuckDB/extension versions are asserted loaded and carried in the assertion
messages (spec 0025 §6: record actual runtime/extension versions).
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.sources import build_connection, load_registry, plan  # noqa: E402
from tests import s3_fixture as fx  # noqa: E402

ICEBERG_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "s3-lakehouse" / "iceberg"
LAKEHOUSE_EXTENSIONS = ("httpfs", "delta", "iceberg", "ducklake")

@pytest.fixture(autouse=True)
def clean_profile_environment(monkeypatch):
    for name in (
        "ARIADE_S1_LOCAL_KEY_ID",
        "ARIADE_S1_LOCAL_SECRET",
        "ARIADE_S1_LOCAL_ENDPOINT",
        "ARIADE_S1_REMOTE_KEY_ID",
        "ARIADE_S1_REMOTE_SECRET",
        "ARIADE_S1_REMOTE_ENDPOINT",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


def runtime_versions() -> dict[str, str]:
    """The actual DuckDB + Lakehouse extension versions (spec 0025 §6): every
    required extension must LOAD in this runtime — a missing capability is a
    refusal, never a skip — and each installed version is reported."""
    con = duckdb.connect()
    try:
        for extension in LAKEHOUSE_EXTENSIONS:
            con.execute(f"LOAD {extension}")
        rows = con.execute(
            "SELECT extension_name, extension_version FROM duckdb_extensions() "
            "WHERE extension_name IN ('httpfs', 'delta', 'iceberg', 'ducklake')",
        ).fetchall()
    finally:
        con.close()
    versions = {"duckdb": duckdb.__version__, **dict(rows)}
    missing = [name for name in (*LAKEHOUSE_EXTENSIONS, "duckdb") if not versions.get(name)]
    assert not missing, f"required Lakehouse runtime capability missing: {missing}"
    return versions


def query_pair(ref_a: str, ref_b: str) -> dict[str, tuple[str, tuple]]:
    """The two per-endpoint checks: A carries the EMEA-filtered oracle triple,
    B the plain count/sum (spec 0025 §7 AC8 independent oracle)."""
    return {
        "a": (
            "SELECT count(*), sum(amount), sum(amount) FILTER (WHERE region = 'EMEA') "
            f"FROM {ref_a}",
            (fx.ORACLE_A["count"], fx.ORACLE_A["sum"], fx.ORACLE_A["emea_sum"]),
        ),
        "b": (
            f"SELECT count(*), sum(amount) FROM {ref_b}",
            (fx.ORACLE_B["count"], fx.ORACLE_B["sum"]),
        ),
    }


def registry_file(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "ariadne.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


# --------------------------------------------------- family fixture preparation

def prepare_delta(endpoint: fx.S3Endpoint, tmp: Path, bucket: str, table: str, rows: list) -> str:
    """A minimal but REAL remote Delta table, reusing the accepted
    ``tests/test_sources.py::delta_table`` preparation: DuckDB writes the
    parquet, the ``_delta_log`` commit (protocol + metaData + add, stdlib
    only) is assembled per the Delta spec against the oracle rows."""
    local = tmp / f"delta-{bucket}.parquet"
    con = duckdb.connect()
    values = ", ".join(str(row) for row in rows)
    con.execute(  # nosemgrep — fixture-authored literal oracle rows only
        f"COPY (SELECT * FROM (VALUES {values}) t(id, amount, region)) "
        f"TO '{local}' (FORMAT PARQUET)"
    )
    con.close()
    data = local.read_bytes()
    schema = {
        "type": "struct",
        "fields": [
            {"name": "id", "type": "integer", "nullable": True, "metadata": {}},
            {"name": "amount", "type": "integer", "nullable": True, "metadata": {}},
            {"name": "region", "type": "string", "nullable": True, "metadata": {}},
        ],
    }
    now = int(time.time() * 1000)
    actions = [
        {"protocol": {"minReaderVersion": 1, "minWriterVersion": 2}},
        {
            "metaData": {
                "id": str(uuid.uuid4()),
                "format": {"provider": "parquet", "options": {}},
                "schemaString": json.dumps(schema),
                "partitionColumns": [],
                "configuration": {},
                "createdTime": now,
            }
        },
        {
            "add": {
                "path": "part-00000.parquet",
                "partitionValues": {},
                "size": len(data),
                "modificationTime": now,
                "dataChange": True,
            }
        },
    ]
    endpoint.put_bytes(f"{bucket}/{table}/part-00000.parquet", data)
    endpoint.put_bytes(
        f"{bucket}/{table}/_delta_log/00000000000000000000.json",
        "".join(json.dumps(action) + "\n" for action in actions).encode(),
    )
    return f"s3://{bucket}/{table}"


def prepare_iceberg(endpoint: fx.S3Endpoint, variant: str, bucket: str, table: str) -> str:
    """Upload the committed independently prepared Iceberg fixture (see
    ``tests/fixtures/s3-lakehouse/iceberg/README.md``) under this endpoint's
    disjoint scope, mirroring its directory layout verbatim."""
    source = ICEBERG_FIXTURES / variant
    expected = {
        "metadata/v1.metadata.json",
        "metadata/manifest-list.avro",
        "metadata/manifest.avro",
        "metadata/version-hint.text",
        "data/data.parquet",
    }
    present = {str(path.relative_to(source)) for path in source.rglob("*") if path.is_file()}
    assert present == expected, f"iceberg fixture {variant} drifted: {sorted(present ^ expected)}"
    for path in sorted(source.rglob("*")):
        if path.is_file():
            endpoint.put_bytes(f"{bucket}/{table}/{path.relative_to(source)}", path.read_bytes())
    return f"s3://{bucket}/{table}"


def prepare_ducklake(
    endpoint: fx.S3Endpoint, tmp: Path, name: str, bucket: str, table: str, rows: list
) -> Path:
    """A REAL existing DuckLake catalog on test-owned data: the FIXTURE (a raw
    connection with the fixture's own secret, never the builder under test)
    creates the local metadata catalog with its remote DATA_PATH recorded
    FIRST and writes the data files to S3; the product later only REOPENS the
    catalog read-only — it never creates a lake, replaces the catalog or
    overrides the recorded data path (spec 0025 §6)."""
    catalog = tmp / f"{name}.ducklake"
    catalog.unlink(missing_ok=True)
    con = duckdb.connect()
    try:
        con.execute("LOAD httpfs")
        con.execute("LOAD ducklake")
        # force real S3 parquet data files instead of inline catalog segments
        # (ducklake inlines tables under 10 rows by default; 0 disables that —
        # fixture-authoring side only, the product never sets this)
        con.execute("SET ducklake_default_data_inlining_row_limit=0")
        endpoint._fixture_secret(con)  # noqa: SLF001 — fixture-authoring side
        con.execute(
            f"ATTACH '{catalog}' AS {name}_fx (TYPE DUCKLAKE, DATA_PATH 's3://{bucket}/{table}')"
        )
        con.execute(
            f"CREATE TABLE {name}_fx.main.orders "
            "(id INTEGER, amount INTEGER, region VARCHAR)"
        )
        values = ", ".join(str(row) for row in rows)
        con.execute(  # nosemgrep — fixture-authored literal oracle rows only
            f"INSERT INTO {name}_fx.main.orders SELECT * FROM (VALUES {values}) "
            "t(id, amount, region)"
        )
        con.execute(f"DETACH {name}_fx")
    finally:
        con.close()
    return catalog


# ------------------------------------------------------------------ the check

@pytest.mark.parametrize("family", ["delta", "iceberg", "ducklake"])
def test_named_profiles_route_lakehouse_reads(tmp_path, monkeypatch, family):
    """Both independently credentialed endpoints in ONE shared connection per
    reader family: the correct independently specified data (60/40 vs 200),
    signed credential routing (the fixture itself rejects wrong secrets and
    global AWS values are deliberately wrong), required metadata/data object
    requests (removing one makes the same registry refuse), no remote writes
    (object inventories unchanged) and — for DuckLake — a LOCAL metadata path
    reopening the EXISTING remote data location without replacement, new
    catalog or DATA_PATH override, with writes denied read-only."""
    fx.require_docker()
    versions = runtime_versions()
    a, b = fx.storage_pair(tmp_path / "fixture")
    try:
        sources: list[dict] = []
        queries: dict[str, tuple[str, tuple]] = {}
        required_object: str = ""
        data_prefixes = {"retail": "", "analytics": ""}

        if family == "delta":
            a_path = prepare_delta(a, tmp_path, "retail", "delta/orders", fx.ORACLE_A_ROWS)
            b_path = prepare_delta(b, tmp_path, "analytics", "delta/metrics", fx.ORACLE_B_ROWS)
            sources = [
                {"name": "lake_a", "type": "delta", "storage": "local", "path": a_path,
                 "table": "orders"},
                {"name": "lake_b", "type": "delta", "storage": "remote", "path": b_path,
                 "table": "metrics"},
            ]
            queries = query_pair("lake_a.orders", "lake_b.metrics")
            required_object = "retail/delta/orders/_delta_log/00000000000000000000.json"
            data_prefixes = {"retail": "retail/delta/", "analytics": "analytics/delta/"}
        elif family == "iceberg":
            a_path = prepare_iceberg(a, "retail", "retail", "iceberg/orders")
            b_path = prepare_iceberg(b, "analytics", "analytics", "iceberg/metrics")
            sources = [
                {"name": "lake_a", "type": "iceberg", "storage": "local", "path": a_path,
                 "table": "orders"},
                {"name": "lake_b", "type": "iceberg", "storage": "remote", "path": b_path,
                 "table": "metrics"},
            ]
            queries = query_pair("lake_a.orders", "lake_b.metrics")
            required_object = "retail/iceberg/orders/data/data.parquet"
            data_prefixes = {"retail": "retail/iceberg/", "analytics": "analytics/iceberg/"}
        else:  # ducklake: LOCAL metadata catalogs, REMOTE recorded data paths
            a_catalog = prepare_ducklake(a, tmp_path, "lake_a", "retail", "ducklake/orders",
                                         fx.ORACLE_A_ROWS)
            b_catalog = prepare_ducklake(b, tmp_path, "lake_b", "analytics", "ducklake/metrics",
                                         fx.ORACLE_B_ROWS)
            sources = [
                {"name": "lake_a", "type": "ducklake", "storage": "local", "path": str(a_catalog)},
                {"name": "lake_b", "type": "ducklake", "storage": "remote", "path": str(b_catalog)},
            ]
            queries = query_pair("lake_a.main.orders", "lake_b.main.orders")
            data_prefixes = {"retail": "retail/ducklake/", "analytics": "analytics/ducklake/"}
            # the required remote object is one of the lake's S3 data files
            required_object = sorted(
                key for key in a.list_prefix("retail/ducklake/orders") if key.endswith(".parquet")
            )[0]

        # the transport authenticity oracle: each endpoint rejects WRONG
        # credentials itself (a signed wrong-secret request is a 403), so a
        # passing read proves the profile's credentials were actually used
        probe = {
            "delta": "retail/delta/orders/part-00000.parquet",
            "iceberg": "retail/iceberg/orders/metadata/manifest.avro",
            "ducklake": required_object,
        }[family]
        assert a.request_rejected("GET", f"{a.endpoint_url}/{probe}")

        # the remote inventories BEFORE the product session (no-write oracle)
        before = {
            bucket: endpoint.list_prefix(prefix)
            for (bucket, prefix), endpoint in (
                (("retail", data_prefixes["retail"]), a),
                (("analytics", data_prefixes["analytics"]), b),
            )
        }
        local_before = (
            sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*.ducklake*"))
            if family == "ducklake"
            else []
        )

        registry_path = registry_file(
            tmp_path, {"storages": fx.profile_definitions(a, b), "sources": sources}
        )
        fx.export_environment(a, b, monkeypatch)  # global AWS values stay WRONG
        registry = load_registry(registry_path)

        if family == "ducklake":
            # the product's ducklake DDL only REOPENS the existing local
            # metadata catalog read-only: no DATA_PATH override, no new catalog
            _, statements = plan(registry)
            attach_sql = " ".join(s for s in statements if "DUCKLAKE" in s)
            assert attach_sql.count("ATTACH") == 2, attach_sql
            assert "DATA_PATH" not in attach_sql, attach_sql
            assert attach_sql.count("READ_ONLY") == 2, attach_sql

        con, catalog = build_connection(registry)
        try:
            got_a = con.execute(queries["a"][0]).fetchone()
            assert got_a == queries["a"][1], f"{family} A read {got_a} via {versions}"
            got_b = con.execute(queries["b"][0]).fetchone()
            assert got_b == queries["b"][1], f"{family} B read {got_b} via {versions}"
            assert {entry["name"] for entry in catalog} == {"lake_a", "lake_b"}
            # data writes are denied on every source surface (read-only views
            # for delta/iceberg, the read-only attach for ducklake)
            for insert in (
                "INSERT INTO lake_a.main.orders VALUES (999, 1, 'EMEA')"
                if family == "ducklake"
                else "INSERT INTO lake_a.orders VALUES (999, 1, 'EMEA')",
                "INSERT INTO lake_b.main.orders VALUES (999, 1, 'EMEA')"
                if family == "ducklake"
                else "INSERT INTO lake_b.metrics VALUES (999, 1, 'EMEA')",
            ):
                with pytest.raises(duckdb.Error):
                    con.execute(insert)
        finally:
            con.close()

        after = {
            bucket: endpoint.list_prefix(prefix)
            for (bucket, prefix), endpoint in (
                (("retail", data_prefixes["retail"]), a),
                (("analytics", data_prefixes["analytics"]), b),
            )
        }
        assert after == before, f"{family}: the product session changed remote objects"
        if family == "ducklake":
            local_after = sorted(
                str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*.ducklake*")
            )
            assert local_after == local_before, "the product created/replaced local catalog files"

        # required metadata/data object requests: deleting the object the
        # reader must fetch makes the SAME registry refuse on a fresh
        # connection — the earlier green read really requested it from the
        # endpoint rather than any cache or local substitute
        a.delete_object(required_object)
        fresh = None
        with pytest.raises(duckdb.Error):
            fresh, _ = build_connection(load_registry(registry_path))
            fresh.execute(queries["a"][0]).fetchall()
        if fresh is not None:
            fresh.close()
    finally:
        fx.stop_pair(a, b)
