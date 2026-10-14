"""The shared local S3-compatible fixture for the storage-profile checks
(issue #71/S1, spec 0025 §§7 AC2–AC5; reused by S2's Lakehouse matrix).

Independent oracle (spec-declared inputs, never observed implementation
output): storage A exposes rows (1,10,'EMEA'), (2,20,'AMER'), (3,30,'EMEA')
— count 3, sum 60, EMEA sum 40; storage B exposes (101,80,'EMEA'),
(102,120,'AMER') — count 2, sum 200. Distinct synthetic key/secret pairs per
endpoint: wrong credentials are rejected by the fixture itself (a signed
request with the wrong secret is a 403), not merely checked for header
presence.

Transport: the locally present ``chrislusf/seaweedfs:4.48`` image (MinIO
cannot be pulled on this host), one container per endpoint on a free port,
with per-endpoint credentials in ``s3.json`` and the 4.48-required
``security.toml`` JWT key. Parquet fixtures are written through a RAW DuckDB
connection with an explicit config-provider secret (fixture-authoring side,
never the Ariadne builder under test); arbitrary bytes (the native DuckDB
catalog) upload through a minimal stdlib SigV4 PUT. Every test owns its full
container lifecycle (start/stop in fixtures, no cross-test reuse) and cleans
up even on failure.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

# The independently specified fixture datasets (issue #71's oracle).
ORACLE_A_ROWS = [(1, 10, "EMEA"), (2, 20, "AMER"), (3, 30, "EMEA")]
ORACLE_B_ROWS = [(101, 80, "EMEA"), (102, 120, "AMER")]
ORACLE_A = {"count": 3, "sum": 60, "emea_sum": 40}
ORACLE_B = {"count": 2, "sum": 200}

_IMAGE = "chrislusf/seaweedfs:4.48"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _sigv4(
    key_id: str, secret: str, region: str, method: str, url: str, payload: bytes = b""
) -> tuple[int, bytes]:
    """One minimal AWS SigV4 request (UNSIGNED-PAYLOAD) — stdlib only, the
    fixture's own client (never the code under test). The canonical request
    signs method, path, the sorted canonical QUERY string and the standard
    headers, so signed list/delete requests carry their query correctly."""
    u = urllib.parse.urlsplit(url)
    # canonical query: pairs decoded from the raw URL, then URI-encoded once
    pairs = urllib.parse.parse_qsl(u.query, keep_blank_values=True) if u.query else []
    canonical_query = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
        for k, v in sorted(pairs)
    )
    now = datetime.datetime.now(datetime.UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    date = now.strftime("%Y%m%d")
    scope = f"{date}/{region}/s3/aws4_request"
    headers = {"host": u.netloc, "x-amz-content-sha256": "UNSIGNED-PAYLOAD", "x-amz-date": stamp}
    signed = "host;x-amz-content-sha256;x-amz-date"
    canonical_headers = "".join(
        f"{name}:{headers[name]}\n" for name in ("host", "x-amz-content-sha256", "x-amz-date")
    )
    canonical = "\n".join(
        [
            method,
            urllib.parse.quote(u.path),
            canonical_query,
            canonical_headers,
            signed,
            "UNSIGNED-PAYLOAD",
        ]
    )
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            stamp,
            scope,
            hashlib.sha256(canonical.encode()).hexdigest(),
        ]
    )

    def keyed(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    key = keyed(keyed(keyed(keyed(f"AWS4{secret}".encode(), date), region), "s3"), "aws4_request")
    signature = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        url,
        data=payload if method == "PUT" else None,
        headers={
            **headers,
            "Authorization": (
                f"AWS4-HMAC-SHA256 Credential={key_id}/{scope}, "
                f"SignedHeaders={signed}, Signature={signature}"
            ),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as error:
        return int(error.code), error.read()


class S3Endpoint:
    """One loopback S3-compatible endpoint: its own container, port and
    synthetic credentials. Created data lives under ``s3://retail/`` /
    ``s3://analytics/`` — the spec's disjoint scopes."""

    def __init__(
        self,
        tmp: Path,
        name: str,
        access_key: str,
        secret_key: str,
        port: int | None,
        *,
        rotated_key: str | None = None,
        rotated_secret: str | None = None,
    ):
        self.name = name
        self.access_key = access_key
        self.secret_key = secret_key
        self.rotated_key = rotated_key
        self.rotated_secret = rotated_secret
        self.port = port or _free_port()
        self.endpoint_url = f"http://127.0.0.1:{self.port}"
        self.hostport = f"127.0.0.1:{self.port}"
        self._tmp = tmp
        self._container = f"ariadne-s1-fx-{name}-{self.port}"

    # ---------------------------------------------------------- lifecycle

    def start(self) -> S3Endpoint:
        self._tmp.mkdir(parents=True, exist_ok=True)
        config = self._tmp / f"{self.name}-s3.json"
        credentials = [
            {"accessKey": self.access_key, "secretKey": self.secret_key},
            *(
                [{"accessKey": self.rotated_key, "secretKey": self.rotated_secret}]
                if self.rotated_key and self.rotated_secret
                else []
            ),
        ]
        actions = ["Read", "Write", "List", "Tagging", "Admin"]
        identities = [
            {"name": "anonymous", "actions": []},
            {"name": self.name, "credentials": [credentials[0]], "actions": actions},
        ]
        if len(credentials) > 1:  # one identity per credential pair: the
            # rotated key is a SECOND identity with the same actions (seaweedfs
            # matches one credential per identity)
            identities.append(
                {
                    "name": f"{self.name}-rotated",
                    "credentials": [credentials[1]],
                    "actions": actions,
                }
            )
        config.write_text(json.dumps({"identities": identities}), encoding="utf-8")
        security = self._tmp / f"{self.name}-security.toml"
        security.write_text('[jwt.filer_signing]\nkey = "fixture"\n', encoding="utf-8")
        config.chmod(0o644)
        security.chmod(0o644)
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                self._container,
                "-p",
                f"{self.port}:8333",
                "-v",
                f"{config}:/etc/seaweedfs/s3.json:ro",
                "-v",
                f"{security}:/data/security.toml:ro",
                _IMAGE,
                "server",
                "-dir",
                "/data",
                "-master.volumeSizeLimitMB=64",
                "-s3",
                "-s3.config=/etc/seaweedfs/s3.json",
                "-s3.port=8333",
            ],
            check=True,
            capture_output=True,
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                status, _ = _sigv4(
                    self.access_key,
                    self.secret_key,
                    "us-east-1",
                    "GET",
                    f"{self.endpoint_url}/",
                )
                if status in (200, 403, 400):  # the S3 gateway answers authenticated requests
                    return self
            except OSError:
                pass
            time.sleep(0.5)
        self.stop()
        raise RuntimeError(f"seaweedfs fixture {self.name} did not come up on {self.endpoint_url}")

    def stop(self) -> None:
        subprocess.run(
            ["docker", "rm", "-f", self._container], capture_output=True, check=False
        )

    def __enter__(self) -> S3Endpoint:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # ------------------------------------------------------------- data

    def _fixture_secret(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("LOAD httpfs")
        con.execute(
            f"CREATE SECRET fixture_{self.name} (TYPE S3, PROVIDER CONFIG, "
            f"KEY_ID '{self.access_key}', SECRET '{self.secret_key}', "
            f"ENDPOINT '{self.hostport}', USE_SSL false, URL_STYLE 'path', "
            f"REGION 'us-east-1')"
        )

    def _put_rows(self, key: str, rows: list[tuple], columns: tuple[str, ...], fmt: str) -> str:
        """Write one object through a RAW fixture connection (the fixture
        authors its own data; the Ariadne builder is never involved)."""
        url = f"s3://{key}"
        values = ", ".join(str(row) for row in rows)
        con = duckdb.connect()
        try:
            self._fixture_secret(con)
            # nosemgrep — fixture-authored literal test rows only (trusted
            # inputs, no caller data); DuckDB COPY takes no bind parameters.
            con.execute(
                f"COPY (SELECT * FROM (VALUES {values}) t({', '.join(columns)})) "
                f"TO '{url}' (FORMAT {fmt})"
            )
        finally:
            con.close()
        return url

    def put_parquet(self, key: str, rows: list[tuple], columns: tuple[str, ...]) -> str:
        return self._put_rows(key, rows, columns, "PARQUET")

    def put_csv(self, key: str, rows: list[tuple], columns: tuple[str, ...]) -> str:
        """A small valid CSV object (the file-reader family fixture)."""
        return self._put_rows(key, rows, columns, "CSV")

    def put_json(self, key: str, rows: list[tuple], columns: tuple[str, ...]) -> str:
        """A small valid JSON object (the file-reader family fixture)."""
        return self._put_rows(key, rows, columns, "JSON")

    def put_bytes(self, key: str, data: bytes) -> str:
        """Upload arbitrary bytes (a native DuckDB catalog file) via SigV4."""
        url = f"{self.endpoint_url}/{key}"
        status, body = _sigv4(
            self.access_key, self.secret_key, "us-east-1", "PUT", url, payload=data
        )
        assert status == 200, f"fixture PUT {key} failed ({status}): {body[:200]!r}"
        return f"s3://{key}"

    def list_prefix(self, key_prefix: str) -> list[str]:
        """Every object key under ``bucket/prefix/…`` (S3 ListObjectsV2, fixture
        client): the remote-object inventory the Lakehouse checks compare
        before/after a product session to prove no remote writes happened."""
        bucket, _, prefix = key_prefix.partition("/")
        keys: list[str] = []
        token = ""
        while True:
            query = f"list-type=2&prefix={urllib.parse.quote(prefix, safe='')}"
            if token:
                query += f"&continuation-token={urllib.parse.quote(token, safe='')}"
            status, body = _sigv4(
                self.access_key, self.secret_key, "us-east-1", "GET",
                f"{self.endpoint_url}/{bucket}?{query}",
            )
            assert status == 200, f"fixture LIST {key_prefix} failed ({status}): {body[:200]!r}"
            root = xml.etree.ElementTree.fromstring(body)
            strip = lambda tag: tag.rsplit("}", 1)[-1]  # noqa: E731 — s3 XML namespace
            keys.extend(
                f"{bucket}/{node.text}" for node in root.iter() if strip(node.tag) == "Key"
            )
            truncated = any(
                strip(node.tag) == "IsTruncated" and (node.text or "").lower() == "true"
                for node in root.iter()
            )
            if not truncated:
                return sorted(keys)
            token = next(
                (node.text or "")
                for node in root.iter()
                if strip(node.tag) in ("NextContinuationToken", "NextMarker")
            )

    def delete_object(self, key: str) -> None:
        """Delete one object (fixture-side removal of a required metadata/data
        object, proving the reader actually requests it rather than caching)."""
        status, body = _sigv4(
            self.access_key, self.secret_key, "us-east-1", "DELETE", f"{self.endpoint_url}/{key}"
        )
        assert status in (200, 204), f"fixture DELETE {key} failed ({status}): {body[:200]!r}"

    def request_rejected(self, method: str, url: str) -> bool:
        """The fixture rejects WRONG credentials (proof the transport checks
        signatures, not just header presence)."""
        status, _ = _sigv4(self.access_key, "wrong-secret", "us-east-1", method, url)
        return status == 403


def storage_pair(tmp: Path) -> tuple[S3Endpoint, S3Endpoint]:
    """Two loopback endpoints with DISTINCT synthetic credentials and the
    spec's disjoint datasets: A serves retail (sum 60), B serves analytics
    (sum 200). The caller owns stopping both (use :func:`stop_pair`)."""
    a = S3Endpoint(tmp, "retail", "retailkey001", "retailsecret001", None).start()
    try:
        b = S3Endpoint(tmp, "analytics", "analyticsk02", "analyticssec02", None).start()
    except BaseException:
        a.stop()
        raise
    try:
        a.put_parquet("retail/orders/orders.parquet", ORACLE_A_ROWS, ("id", "amount", "region"))
        b.put_parquet(
            "analytics/metrics/metrics.parquet", ORACLE_B_ROWS, ("id", "amount", "region")
        )
    except BaseException:
        stop_pair(a, b)
        raise
    return a, b


def stop_pair(*endpoints: S3Endpoint) -> None:
    for endpoint in endpoints:
        endpoint.stop()


def native_catalog_bytes(rows: list[tuple]) -> bytes:
    """A real native DuckDB catalog file with the given rows (spec 0022's
    hand-specified shape), as bytes for ``put_bytes`` upload."""
    path = Path(os.environ.get("ARIADE_S3_FX_DIR", "/tmp")) / f"native-{os.getpid()}.duckdb"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE main.orders (id INTEGER, amount INTEGER, region VARCHAR)")
    con.executemany("INSERT INTO main.orders VALUES (?, ?, ?)", rows)
    con.close()
    data = path.read_bytes()
    path.unlink(missing_ok=True)
    return data


def native_view_catalog_bytes(endpoint: S3Endpoint, s3_parquet_url: str) -> bytes:
    """A real native DuckDB catalog whose VIEW reads remote S3 backing files
    (issue #71's native-catalog/backing-file journey): the view definition
    references the s3:// parquet URL and embeds NO credentials. DuckDB binds
    the view at creation, so the FIXTURE's own temporary secret serves that
    bind-time metadata read (session-scoped — nothing is persisted in the
    catalog); later, the shared session's named profile serves the attached
    view's binding and data reads. Returned as bytes for ``put_bytes``."""
    path = Path(os.environ.get("ARIADE_S3_FX_DIR", "/tmp")) / f"nativeview-{os.getpid()}.duckdb"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    con = duckdb.connect(str(path))
    try:
        endpoint._fixture_secret(con)
        con.execute(
            "CREATE VIEW main.backing_orders AS SELECT * FROM "
            f"read_parquet('{s3_parquet_url}')"
        )
    finally:
        con.close()
    data = path.read_bytes()
    path.unlink(missing_ok=True)
    return data


def require_docker() -> None:
    """The live S3 checks are REQUIRED (spec 0025 §§7 AC2/AC5): a missing
    transport capability blocks the check — it is never silently skipped."""
    try:
        probe = subprocess.run(
            ["docker", "version", "--format", "{{.Client.Version}}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            "the live S3-compatible fixture requires a working Docker runtime "
            f"(spec 0025 §7 AC2/AC5 — the check is blocked, not skipped): {exc}"
        ) from None
    if probe.returncode != 0:
        raise RuntimeError(
            "the live S3-compatible fixture requires a working Docker runtime "
            f"(spec 0025 §7 AC2/AC5 — the check is blocked, not skipped): "
            f"{probe.stderr.strip()[:200]}"
        )


_SECRET_VALUE_RE = None  # tests assert on explicit synthetic values instead


def assert_no_secret_values(text: str, values: list[str]) -> None:
    """Fail naming every leaked synthetic secret value (the redaction oracle)."""
    leaked = [value for value in values if value and value in text]
    assert not leaked, f"secret value(s) leaked into output: {leaked}"


def profile_definitions(a: S3Endpoint, b: S3Endpoint) -> dict:
    """The canonical two-profile declaration (env-var NAMES only) for the
    disjoint s3://retail/ and s3://analytics/ scopes."""
    return {
        "local": {
            "type": "s3",
            "access_key_id_env": "ARIADE_S1_LOCAL_KEY_ID",
            "secret_access_key_env": "ARIADE_S1_LOCAL_SECRET",
            "endpoint_url_env": "ARIADE_S1_LOCAL_ENDPOINT",
            "url_style": "path",
            "scopes": ["s3://retail/"],
        },
        "remote": {
            "type": "s3",
            "access_key_id_env": "ARIADE_S1_REMOTE_KEY_ID",
            "secret_access_key_env": "ARIADE_S1_REMOTE_SECRET",
            "endpoint_url_env": "ARIADE_S1_REMOTE_ENDPOINT",
            "scopes": ["s3://analytics/"],
        },
    }


def export_environment(a: S3Endpoint, b: S3Endpoint, monkeypatch) -> None:
    """Populate the process environment for the two profiles (deliberately
    WRONG global AWS values so they cannot hide missing profile config)."""
    monkeypatch.setenv("ARIADE_S1_LOCAL_KEY_ID", a.access_key)
    monkeypatch.setenv("ARIADE_S1_LOCAL_SECRET", a.secret_key)
    monkeypatch.setenv("ARIADE_S1_LOCAL_ENDPOINT", a.endpoint_url)
    monkeypatch.setenv("ARIADE_S1_REMOTE_KEY_ID", b.access_key)
    monkeypatch.setenv("ARIADE_S1_REMOTE_SECRET", b.secret_key)
    monkeypatch.setenv("ARIADE_S1_REMOTE_ENDPOINT", b.endpoint_url)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAGLOBALWRONG")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "globalwrongsecret")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
