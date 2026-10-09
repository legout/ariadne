"""ADR-0010 source registry + shared connection builder (spec rev 9 §8.20).

Tiered per the ADR: LIVE fixtures for sqlite/csv/json/parquet/delta (every
fixture written locally — sqlite3/DuckDB for the data, the delta transaction
log hand-assembled over a DuckDB-written parquet because duckdb 1.5.5's delta
extension is read-only), each built through the registry, queried through the
view, rows asserted. Exact STATEMENT-CONSTRUCTION tests for iceberg/ducklake/
postgres/httpfs (mock duckdb.connect; the executed statement sequence is
asserted verbatim, including postgres env resolution). Registry validation
(inline-connection rejection per ADR-0010, unknown type, slug enforcement) and
one serve.py integration over a sqlite+parquet registry. No network anywhere.
"""

import asyncio
import json
import sqlite3
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

from ariadne.serve import Facade  # noqa: E402
from ariadne.sources import (  # noqa: E402
    build_connection,
    default_registry_path,
    implicit_registry,
    load_registry,
)

# ---------------------------------------------------------------- fixtures


def write_registry(tmp_path: Path, sources: list[dict], name: str = "ariadne.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump({"sources": sources}, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def sqlite_db(tmp_path):
    """A demo SQLite database written locally (stdlib sqlite3)."""
    db = tmp_path / "demo.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, amount REAL, region TEXT)")
    conn.executemany(
        "INSERT INTO orders VALUES (?, ?, ?)",
        [(1, 10.0, "EMEA"), (2, 20.0, "AMER"), (3, 30.0, "EMEA")],
    )
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def duck():
    con = duckdb.connect()
    yield con
    con.close()


def delta_table(tmp_path: Path, name: str = "lake_orders") -> Path:
    """A minimal but REAL delta table: DuckDB writes the parquet, the _delta_log
    commit (protocol + metaData + add) is assembled per the Delta spec — the
    1.5.5 delta extension is read-only, so the log is hand-written (stdlib only)."""
    table_dir = tmp_path / name
    (table_dir / "_delta_log").mkdir(parents=True)
    duckdb.connect().execute(  # data itself is written by DuckDB
        f"COPY (SELECT * FROM (VALUES (1, 'a'), (2, 'b'), (3, 'c')) t(id, label)) "
        f"TO '{table_dir / 'part-00000.parquet'}' (FORMAT PARQUET)"
    ).close()
    schema = {
        "type": "struct",
        "fields": [
            {"name": "id", "type": "integer", "nullable": True, "metadata": {}},
            {"name": "label", "type": "string", "nullable": True, "metadata": {}},
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
                "size": (table_dir / "part-00000.parquet").stat().st_size,
                "modificationTime": now,
                "dataChange": True,
            }
        },
    ]
    (table_dir / "_delta_log" / "00000000000000000000.json").write_text(
        "".join(json.dumps(a) + "\n" for a in actions), encoding="utf-8"
    )
    return table_dir


# ------------------------------------------------------- live: sqlite/parquet


def test_sqlite_attach_live(tmp_path, sqlite_db):
    reg = write_registry(tmp_path, [{"name": "demo", "type": "sqlite", "path": str(sqlite_db)}])
    con, catalog = build_connection(load_registry(reg))
    try:
        assert con.execute("SELECT COUNT(*), SUM(amount) FROM demo.orders").fetchone() == (
            3,
            60.0,
        )
        (entry,) = catalog
        assert entry["name"] == "demo" and entry["type"] == "sqlite"
        (table,) = entry["tables"]
        assert table["name"] == "orders"
        assert [c["name"] for c in table["columns"]] == ["id", "amount", "region"]
    finally:
        con.close()


def test_parquet_file_and_glob_live(tmp_path, duck):
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    duck.execute(
        f"COPY (SELECT 1 AS x UNION ALL SELECT 2) TO '{events_dir / 'p1.parquet'}' (FORMAT PARQUET)"
    )
    duck.execute(
        f"COPY (SELECT 3 AS x UNION ALL SELECT 4) TO '{events_dir / 'p2.parquet'}' (FORMAT PARQUET)"
    )
    duck.execute(f"COPY (SELECT 9 AS single) TO '{tmp_path / 'solo.parquet'}' (FORMAT PARQUET)")
    reg = write_registry(
        tmp_path,
        [
            # glob: two files, ONE view, named by the registry entry
            {
                "name": "events",
                "type": "parquet",
                "path": f"{events_dir}/*.parquet",
                "table": "readings",
            },
            # single file: view named by the file stem
            {"name": "solo", "type": "parquet", "path": str(tmp_path / "solo.parquet")},
        ],
    )
    con, catalog = build_connection(load_registry(reg))
    try:
        assert con.execute("SELECT COUNT(*), SUM(x) FROM events.readings").fetchone() == (
            4,
            10,
        )
        assert con.execute("SELECT single FROM solo.solo").fetchall() == [(9,)]
        by_name = {e["name"]: e for e in catalog}
        assert [t["name"] for t in by_name["events"]["tables"]] == ["readings"]
        assert [t["name"] for t in by_name["solo"]["tables"]] == ["solo"]
    finally:
        con.close()


# ------------------------------------------------------ live: csv/json/delta


def test_csv_live(tmp_path, duck):
    duck.execute(
        f"COPY (SELECT * FROM (VALUES ('EMEA', 10.5), ('AMER', 3.5)) t(region, n)) "
        f"TO '{tmp_path / 'orders.csv'}' (FORMAT CSV, HEADER)"
    )
    reg = write_registry(
        tmp_path, [{"name": "raw", "type": "csv", "path": str(tmp_path / "orders.csv")}]
    )
    con, catalog = build_connection(load_registry(reg))
    try:
        assert con.execute(
            "SELECT region, SUM(n) FROM raw.orders GROUP BY region ORDER BY 1"
        ).fetchall() == [("AMER", 3.5), ("EMEA", 10.5)]
        (entry,) = catalog
        (table,) = entry["tables"]
        assert table["name"] == "orders"  # derived from the file stem
        assert {c["name"] for c in table["columns"]} == {"region", "n"}
    finally:
        con.close()


def test_json_live(tmp_path, duck):
    duck.execute(
        f"COPY (SELECT * FROM (VALUES ('a', 1), ('b', 2)) t(label, n)) "
        f"TO '{tmp_path / 'tags.json'}' (FORMAT JSON)"
    )
    reg = write_registry(
        tmp_path, [{"name": "tags", "type": "json", "path": str(tmp_path / "tags.json")}]
    )
    con, _ = build_connection(load_registry(reg))
    try:
        assert con.execute("SELECT SUM(n) FROM tags.tags").fetchone() == (3,)
    finally:
        con.close()


def test_delta_live(tmp_path):
    table_dir = delta_table(tmp_path)
    reg = write_registry(tmp_path, [{"name": "lake", "type": "delta", "path": str(table_dir)}])
    con, catalog = build_connection(load_registry(reg))
    try:
        assert con.execute("SELECT COUNT(*), SUM(id) FROM lake.lake_orders").fetchone() == (3, 6)
        (entry,) = catalog
        (table,) = entry["tables"]
        assert table["name"] == "lake_orders"  # derived from the directory stem
    finally:
        con.close()


# --------------------------------- statement construction (mock duckdb.connect)


class RecordingConnection:
    """Stands in for duckdb.connect(): ``statements`` records every LOAD/DDL
    statement verbatim (the builder's plan); catalog-introspection SELECTs are
    kept in ``all_statements`` and return empty results."""

    def __init__(self):
        self.statements: list[str] = []
        self.all_statements: list[str] = []

    def execute(self, sql, *args):
        self.all_statements.append(sql)
        if not sql.lstrip().upper().startswith("SELECT"):
            self.statements.append(sql)
            return None
        return type("R", (), {"fetchall": lambda self: []})()

    def close(self):
        pass


@pytest.fixture
def recorded(monkeypatch):
    con = RecordingConnection()
    monkeypatch.setattr(duckdb, "connect", lambda *a, **k: con)
    return con


def test_iceberg_statements(recorded, tmp_path):
    reg = write_registry(
        tmp_path,
        [{"name": "ice", "type": "iceberg", "path": "/data/warehouse/sales", "table": "sales"}],
    )
    con, catalog = build_connection(load_registry(reg))
    assert isinstance(con, RecordingConnection)
    assert con.statements == [
        "LOAD iceberg",
        "CREATE SCHEMA ice",
        "CREATE VIEW ice.sales AS SELECT * FROM iceberg_scan('/data/warehouse/sales')",
    ]
    assert catalog == [{"name": "ice", "type": "iceberg", "tables": []}]


def test_ducklake_statements(recorded, tmp_path):
    reg = write_registry(
        tmp_path, [{"name": "dl", "type": "ducklake", "path": "ducklake:warehouse.ducklake"}]
    )
    con, _ = build_connection(load_registry(reg))
    assert isinstance(con, RecordingConnection)
    assert con.statements == [
        "LOAD ducklake",
        "ATTACH 'ducklake:warehouse.ducklake' AS dl (TYPE DUCKLAKE, READ_ONLY)",
    ]


def test_postgres_statements(recorded, monkeypatch, tmp_path):
    monkeypatch.setenv("ARIADNE_PG_DSN", "dbname=warehouse user=ro")
    reg = write_registry(
        tmp_path, [{"name": "pg", "type": "postgres", "connection_env": "ARIADNE_PG_DSN"}]
    )
    con, catalog = build_connection(load_registry(reg))
    assert isinstance(con, RecordingConnection)
    assert con.statements == [
        "LOAD postgres",
        "ATTACH 'dbname=warehouse user=ro' AS pg (TYPE POSTGRES, READ_ONLY)",
    ]
    assert catalog == [{"name": "pg", "type": "postgres", "tables": []}]


def test_postgres_missing_env_names_the_variable(recorded, monkeypatch, tmp_path):
    monkeypatch.delenv("ARIADNE_PG_DSN", raising=False)
    reg = write_registry(
        tmp_path, [{"name": "pg", "type": "postgres", "connection_env": "ARIADNE_PG_DSN"}]
    )
    with pytest.raises(ValueError, match="ARIADNE_PG_DSN"):
        build_connection(load_registry(reg))


# ------------------------------------------------------------ DSN redaction


def test_attach_failure_error_never_carries_the_dsn(monkeypatch, tmp_path):
    """A failing postgres ATTACH re-raises with the DSN redacted: the password
    — and the full DSN — never appear in an exception message (ADR-0010)."""
    dsn = "postgresql://ro:s3cret@db.internal:5432/prod"
    monkeypatch.setenv("ARIADNE_PG_DSN", dsn)
    reg = write_registry(
        tmp_path, [{"name": "pg", "type": "postgres", "connection_env": "ARIADNE_PG_DSN"}]
    )

    class ExplodingConnection:
        def execute(self, sql, *args):
            if sql.lstrip().upper().startswith("ATTACH"):
                raise RuntimeError(f"Connection error: unable to attach: {sql}")
            return type("R", (), {"fetchall": lambda self: []})()

        def close(self):
            pass

    monkeypatch.setattr(duckdb, "connect", lambda *a, **k: ExplodingConnection())
    with pytest.raises(RuntimeError) as excinfo:
        build_connection(load_registry(reg))
    message = str(excinfo.value)
    assert "s3cret" not in message  # password never survives
    assert dsn not in message  # the full DSN is gone
    assert "postgresql://ro:***@db.internal:5432/prod" in message  # redaction marker


def test_quote_bearing_dsn_error_does_not_echo_the_value(monkeypatch, tmp_path):
    monkeypatch.setenv("ARIADNE_PG_DSN", "postgres://u:pa'ss@h/db")
    reg = write_registry(
        tmp_path, [{"name": "pg", "type": "postgres", "connection_env": "ARIADNE_PG_DSN"}]
    )
    with pytest.raises(ValueError, match="quote character") as excinfo:
        build_connection(load_registry(reg))
    assert "pa'ss" not in str(excinfo.value)


def test_remote_parquet_uses_operator_ca_bundle(monkeypatch, tmp_path):
    """An internal S3 endpoint needs the CA bundle on DuckDB's connection."""
    ca = tmp_path / "corporate-ca.pem"
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))
    seen = {}

    def connect(*args, **kwargs):
        seen.update(kwargs)
        return RecordingConnection()

    monkeypatch.setattr(duckdb, "connect", connect)
    reg = write_registry(
        tmp_path,
        [
            {
                "name": "remote",
                "type": "parquet",
                "path": "s3://bucket/orders/*.parquet",
                "table": "orders",
            }
        ],
    )
    build_connection(load_registry(reg))
    assert seen["config"] == {"ca_cert_file": str(ca)}


def test_remote_parquet_loads_httpfs_once(recorded, tmp_path):
    """Two remote file sources -> httpfs LOADed exactly once, first."""
    reg = write_registry(
        tmp_path,
        [
            {"name": "a", "type": "parquet", "path": "https://cdn.example.com/a.parquet"},
            {"name": "b", "type": "csv", "path": "s3://bucket/b.csv"},
        ],
    )
    con, _ = build_connection(load_registry(reg))
    assert isinstance(con, RecordingConnection)
    loads = [s for s in con.statements if s.startswith("LOAD")]
    assert loads == ["LOAD httpfs"]
    assert con.statements[0] == "LOAD httpfs"
    assert con.statements[2] == (
        "CREATE VIEW a.a AS SELECT * FROM read_parquet('https://cdn.example.com/a.parquet')"
    )
    assert con.statements[4] == (
        "CREATE VIEW b.b AS SELECT * FROM read_csv_auto('s3://bucket/b.csv')"
    )


def test_writable_build_drops_read_only(recorded, tmp_path):
    """build_connection(read_only=False): attaches lose the READ_ONLY suffix."""
    reg = write_registry(tmp_path, [{"name": "d", "type": "ducklake", "path": "x.ducklake"}])
    con, _ = build_connection(load_registry(reg), read_only=False)
    assert isinstance(con, RecordingConnection)
    assert con.statements == [
        "LOAD ducklake",
        f"ATTACH '{tmp_path / 'x.ducklake'}' AS d (TYPE DUCKLAKE)",  # resolved vs registry dir
    ]


# --------------------------------------------------------- registry validation


def test_inline_connection_rejected_naming_adr(tmp_path):
    reg = write_registry(
        tmp_path,
        [{"name": "pg", "type": "postgres", "connection": "postgresql://u:p@h/db"}],
    )
    with pytest.raises(ValueError, match="ADR-0010"):
        load_registry(reg)


def test_connection_env_dsn_shaped_rejected_as_inline(tmp_path):
    reg = write_registry(
        tmp_path,
        [{"name": "pg", "type": "postgres", "connection_env": "postgresql://u:p@h/db"}],
    )
    with pytest.raises(ValueError, match="ADR-0010"):
        load_registry(reg)


def test_unknown_type_rejected(tmp_path):
    reg = write_registry(tmp_path, [{"name": "x", "type": "mongodb", "path": "data/x"}])
    with pytest.raises(ValueError, match="unknown type 'mongodb'"):
        load_registry(reg)


@pytest.mark.parametrize(
    ("key", "source_type"),
    [
        ("dsn", "postgres"),
        ("connection_string", "postgres"),
        ("path", "sqlite"),
        ("table", "csv"),
    ],
)
def test_inline_dsn_under_any_key_rejected(tmp_path, key, source_type):
    """dsn:/connection_string: are not loopholes: a postgres://-shaped value
    under ANY key of ANY source entry is an ADR-0010 error naming the rule."""
    reg = write_registry(
        tmp_path, [{"name": "pg", "type": source_type, key: "postgresql://u:p@h/db"}]
    )
    with pytest.raises(ValueError, match="ADR-0010"):
        load_registry(reg)


def test_credentialed_url_userinfo_rejected_naming_adr(tmp_path):
    """URL userinfo is an inline credential (ADR-0010): https://user:pass@host
    under any entry key fails loudly at the registry itself, like a DSN."""
    reg = write_registry(
        tmp_path,
        [{"name": "cdn", "type": "parquet", "path": "https://ro:s3cret@cdn/e.parquet"}],
    )
    with pytest.raises(ValueError, match="ADR-0010"):
        load_registry(reg)


def test_unknown_keys_rejected(tmp_path):
    """Strict entry schema: freestyle keys fail loudly instead of passing."""
    reg = write_registry(tmp_path, [{"name": "a", "type": "sqlite", "path": "x.db", "extra": 1}])
    with pytest.raises(ValueError, match=r"unknown key\(s\) \['extra'\]"):
        load_registry(reg)


@pytest.mark.parametrize("bad", ["Orders", "9lives", "orders-v2", ""])
def test_name_must_be_slug(tmp_path, bad):
    reg = write_registry(tmp_path, [{"name": bad, "type": "sqlite", "path": "x.db"}])
    with pytest.raises(ValueError, match="lowercase slug"):
        load_registry(reg)


def test_missing_path_and_missing_connection_env(tmp_path):
    with pytest.raises(ValueError, match="type csv requires path"):
        load_registry(write_registry(tmp_path, [{"name": "a", "type": "csv"}]))
    with pytest.raises(ValueError, match="requires connection_env"):
        load_registry(write_registry(tmp_path, [{"name": "b", "type": "postgres"}]))


def test_glob_without_table_rejected(tmp_path):
    reg = write_registry(tmp_path, [{"name": "e", "type": "parquet", "path": "data/*.parquet"}])
    with pytest.raises(ValueError, match="explicit table: name"):
        load_registry(reg)


def test_duplicate_names_rejected(tmp_path):
    reg = write_registry(
        tmp_path,
        [
            {"name": "demo", "type": "sqlite", "path": "a.db"},
            {"name": "demo", "type": "sqlite", "path": "b.db"},
        ],
    )
    with pytest.raises(ValueError, match="duplicate source name 'demo'"):
        load_registry(reg)


# ------------------------------------------------- default resolution + legacy


def test_default_registry_path_resolution(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert default_registry_path() is None  # nothing present
    (tmp_path / "ariadne.yaml").write_text(
        "# only comments — the scaffolded template\n", encoding="utf-8"
    )
    assert default_registry_path() is None  # template counts as absent
    write_registry(tmp_path, [{"name": "demo", "type": "sqlite", "path": "data/demo.db"}])
    resolved = default_registry_path()
    assert resolved is not None and resolved.name == "ariadne.yaml" and resolved.is_file()
    assert default_registry_path("other.yaml") == Path("other.yaml")  # explicit wins
    (tmp_path / "broken.yaml").write_text("sources: [unparsable", encoding="utf-8")
    assert default_registry_path("broken.yaml") == Path("broken.yaml")  # let it raise
    # an explicit --db always suppresses the ambient probe; --sources beats --db
    assert default_registry_path(None, "x.db") is None
    assert default_registry_path("r.yaml", "x.db") == Path("r.yaml")


def test_implicit_registry_is_legacy_demo_shorthand():
    registry = implicit_registry("data/demo.db")
    assert registry.path is None
    (source,) = registry.sources
    assert (source.name, source.type, source.path) == ("demo", "sqlite", "data/demo.db")


# ------------------------------------------------ registry-relative path base


def test_relative_paths_resolve_against_the_registry_file(tmp_path, monkeypatch):
    """init.py's promise: registry paths are relative to the registry's
    directory, not the process cwd (makes --sources cwd-independent)."""
    dir_a = tmp_path / "a"
    (dir_a / "data").mkdir(parents=True)
    db = dir_a / "data" / "demo.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t (x INTEGER)")
    con.commit()
    con.close()
    reg = write_registry(dir_a, [{"name": "demo", "type": "sqlite", "path": "data/demo.db"}])

    (tmp_path / "b").mkdir()
    monkeypatch.chdir(tmp_path / "b")  # unrelated cwd
    registry = load_registry(reg)
    assert registry.sources[0].path == str(db)  # resolved under A
    con, _ = build_connection(registry)
    try:
        assert con.execute("SELECT COUNT(*) FROM demo.t").fetchone() == (0,)
    finally:
        con.close()


def test_absolute_and_scheme_paths_pass_through_untouched(tmp_path):
    reg = write_registry(
        tmp_path,
        [
            {"name": "abs", "type": "sqlite", "path": "/data/abs.db"},
            {"name": "web", "type": "parquet", "path": "https://cdn/x.parquet", "table": "web"},
            {"name": "dl", "type": "ducklake", "path": "ducklake:w.ducklake"},
        ],
    )
    paths = {s.name: s.path for s in load_registry(reg).sources}
    assert paths == {
        "abs": "/data/abs.db",
        "web": "https://cdn/x.parquet",
        "dl": "ducklake:w.ducklake",
    }


# ------------------------------------------------------- serve.py integration


MINIMAL_OSI = """\
version: 0.2.0.dev0
semantic_model:
  - name: orders
    description: Orders model
    datasets:
      - name: orders
        source: >-
          SELECT id, amount FROM demo.main.orders
        primary_key: [id]
        fields:
          - name: id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: id
          - name: amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: amount
    metrics:
      - name: total_amount
        description: Sum of order amounts
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(amount)
"""


def test_facade_over_sqlite_plus_parquet_registry(tmp_path, sqlite_db, duck):
    (tmp_path / "semantic_layer" / "models").mkdir(parents=True)
    (tmp_path / "semantic_layer" / "models" / "orders.yml").write_text(MINIMAL_OSI)
    duck.execute(
        f"COPY (SELECT 'up' AS status, 2 AS n UNION ALL SELECT 'down', 3) "
        f"TO '{tmp_path / 'status.parquet'}' (FORMAT PARQUET)"
    ).close()
    reg = write_registry(
        tmp_path,
        [
            {"name": "demo", "type": "sqlite", "path": str(sqlite_db)},
            {"name": "events", "type": "parquet", "path": str(tmp_path / "status.parquet")},
        ],
    )
    facade = Facade(
        tmp_path / "semantic_layer",
        tmp_path / "context_layer",
        sqlite_db,
        staging_dir=tmp_path / "staging",
        sources=reg,
    )
    # governed metric over the sqlite model, executed on the registry connection
    result = asyncio.run(facade.get_metric("total_amount"))
    assert result["governed"] is True
    assert result["rows"] == [{"total_amount": 60.0}]
    # list_datasets reflects the FULL multi-source catalog, qualified per source
    datasets = {d["name"]: d for d in asyncio.run(facade.list_datasets())}
    assert set(datasets) == {"demo.orders", "events.status"}
    assert [c["name"] for c in datasets["events.status"]["columns"]] == ["status", "n"]
