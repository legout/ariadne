"""Spec 0022 AC4/AC5 remote evidence: a real stdlib loopback HTTP transport —
range-capable (HEAD + single byte ranges with 206/Content-Range), serving an
actual native view-only DuckDB catalog and its separately written Parquet
backing file. This is the spec's permitted local HTTP fixture: it proves the
shared builder attaches a remote catalog through httpfs and binds/reads its
view's backing data with the independently specified fixture rows. It is NOT
evidence about authenticated TLS/S3 production endpoints (reported unverified
without separate operator context). No external endpoint, no server framework.
"""

import http.server
import os
import sys
import threading
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.sources import build_connection, load_registry  # noqa: E402

# The spec's hand-specified rows: count 3, total 60.0, EMEA total 40.0 —
# declared inputs and arithmetic, never values copied from query output.
FIXTURE_ROWS = [(1, 10.0, "EMEA"), (2, 20.0, "AMER"), (3, 30.0, "EMEA")]

_SERVE_ROOT: Path | None = None


class _RangeHandler(http.server.SimpleHTTPRequestHandler):
    """The minimum a remote DuckDB catalog/parquet reader needs from an HTTP
    server: HEAD, single byte ranges answered 206 with Content-Range, explicit
    404s, and deterministic keep-alive behavior — stdlib only."""

    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(_SERVE_ROOT), **kwargs)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 — stdlib name
        pass  # quiet: failures assert on responses, not logs

    def _serve(self, send_body: bool) -> None:
        path = self.translate_path(self.path)
        if not os.path.isfile(path):
            served.append((self.command, 404))
            self.send_error(404)
            return
        size = os.path.getsize(path)
        header = self.headers.get("Range")
        start, end = 0, size - 1
        if header:
            units, _, spec = header.partition("=")
            first, _, last = spec.partition("-")
            if units.strip() != "bytes" or not first or "," in spec:
                self.send_error(416, "single-unit byte ranges only")
                return
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
            if start < 0 or start > end or start >= size:
                self.send_error(416, "range outside the resource")
                return
        served.append((self.command, 206 if header else 200))
        self.send_response(206 if header else 200)
        if header:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        if send_body and end >= start:
            with open(path, "rb") as handle:
                handle.seek(start)
                self.wfile.write(handle.read(end - start + 1))

    def do_GET(self) -> None:  # noqa: N802 — stdlib dispatch name
        self._serve(send_body=True)

    def do_HEAD(self) -> None:  # noqa: N802 — stdlib dispatch name
        self._serve(send_body=False)


served: list[tuple[str, int]] = []


@pytest.fixture
def loopback(tmp_path):
    """A real local HTTP server on an ephemeral loopback port serving tmp_path;
    shut down deterministically (no leaked listener across tests)."""
    global _SERVE_ROOT, served
    _SERVE_ROOT = tmp_path
    served = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RangeHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", tmp_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        _SERVE_ROOT = None


@pytest.fixture
def tracked_connections(monkeypatch):
    """Every real duckdb.connect() the builder performs, tracked so a refused
    setup can be proven to have CLOSED its owned connection."""
    created = []
    real_connect = duckdb.connect

    def tracking(*args, **kwargs):
        con = real_connect(*args, **kwargs)
        created.append(con)
        return con

    monkeypatch.setattr(duckdb, "connect", tracking)
    return created


def write_backing_parquet(path: Path) -> Path:
    """The separately stored backing data: the spec's three rows with explicit
    column types, written by a local DuckDB (never served from inside a view)."""
    con = duckdb.connect()
    con.execute(
        f"COPY (SELECT CAST(id AS INTEGER) AS id, CAST(amount AS DOUBLE) AS amount, "
        f"CAST(region AS VARCHAR) AS region FROM (VALUES (1, 10.0, 'EMEA'), "
        f"(2, 20.0, 'AMER'), (3, 30.0, 'EMEA')) t(id, amount, region)) "
        f"TO '{path}' (FORMAT PARQUET)"
    )
    con.close()
    return path


def write_view_catalog(path: Path, backing_url: str) -> Path:
    """A real view-only native catalog whose one view reads the explicit
    backing URL (created while the loopback server answers, so the create-time
    bind succeeds and only later reads depend on the transport)."""
    con = duckdb.connect(str(path))
    con.execute(f"CREATE VIEW main.orders AS SELECT * FROM read_parquet('{backing_url}')")
    con.close()
    return path


def remote_registry(tmp_path: Path, url: str, name: str = "rail") -> Path:
    registry = tmp_path / "ariadne.yaml"
    registry.write_text(
        yaml.safe_dump({"sources": [{"name": name, "type": "duckdb", "path": url}]}),
        encoding="utf-8",
    )
    return registry


def test_remote_duckdb_catalog_reads_backing_data(loopback):
    """Spec 0022 AC4: attach the served view-only catalog through the shared
    builder and query the SEPARATELY hosted backing data — the spec's fixture
    rows, count 3 / total 60.0 / EMEA 40.0."""
    url, root = loopback
    write_backing_parquet(root / "backing.parquet")
    catalog_file = write_view_catalog(root / "catalog.duckdb", f"{url}/backing.parquet")
    assert catalog_file.is_file()
    registry = remote_registry(root, f"{url}/catalog.duckdb")

    con, catalog = build_connection(load_registry(registry))
    try:
        assert (
            con.execute("SELECT id, amount, region FROM rail.main.orders ORDER BY id").fetchall()
            == FIXTURE_ROWS
        )
        assert con.execute("SELECT COUNT(*), SUM(amount) FROM rail.main.orders").fetchone() == (
            3,
            60.0,
        )
        assert con.execute(
            "SELECT SUM(amount) FROM rail.main.orders WHERE region = 'EMEA'"
        ).fetchone() == (40.0,)
        (entry,) = catalog
        assert (entry["name"], entry["type"]) == ("rail", "duckdb")
        (table,) = entry["tables"]
        assert (table["catalog"], table["schema"], table["ref"]) == ("rail", "main", "rail.main")
        assert [c["name"] for c in table["columns"]] == ["id", "amount", "region"]
    finally:
        con.close()
    # the transport really spoke range/HEAD HTTP to the loopback server
    methods = {method for method, _ in served}
    assert {"GET"} <= methods and any(status == 206 for _, status in served)


def test_remote_missing_catalog_refuses_setup_and_closes(loopback, tracked_connections):
    """Spec 0022 AC5: a catalog the transport cannot deliver (404) is a SETUP
    refusal — the incomplete connection is closed, never a partial session."""
    url, root = loopback
    registry = remote_registry(root, f"{url}/absent.duckdb")
    with pytest.raises(Exception, match="does not exist|IO Error"):
        build_connection(load_registry(registry))
    assert tracked_connections, "a connection was opened and must now be closed"
    with pytest.raises(Exception, match="Connection Error|already closed|Cannot call"):
        tracked_connections[0].execute("SELECT 1")


def test_remote_view_with_missing_backing_refuses_setup_at_bind(loopback, tracked_connections):
    """Spec 0022 AC5: a view whose binding requires missing backing data fails
    DURING bounded setup (the builder's required view binding), not as a later
    query failure — and the refused setup leaves its connection closed."""
    url, root = loopback
    write_backing_parquet(root / "backing.parquet")
    write_view_catalog(root / "catalog.duckdb", f"{url}/backing.parquet")
    (root / "backing.parquet").unlink()  # the served backing is gone; catalog stays
    registry = remote_registry(root, f"{url}/catalog.duckdb")
    with pytest.raises(Exception, match="404|HTTP Error"):
        build_connection(load_registry(registry))
    assert tracked_connections, "a connection was opened and must now be closed"
    with pytest.raises(Exception, match="Connection Error|already closed|Cannot call"):
        tracked_connections[0].execute("SELECT 1")
    # the refused setup still served the catalog itself; only the backing was gone
    assert any(status == 404 for _, status in served)
