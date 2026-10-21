"""S3-compatible integration coverage for CLI remote-LanceDB binding (issue #162).

Proves the standalone ``lumio-wiki search`` command consumes the active S3
Published Version's remote LanceDB index through public seams only: publish a
real version (with and without ``--retrieval lancedb``), then run the CLI
against ``s3://bucket/prefix`` with ``LUMIO_RETRIEVAL_BACKEND=lancedb``.

Skips the whole module unless ``LUMIO_S3_ENDPOINT`` is configured, mirroring
the other S3-compatible suites.
"""

from __future__ import annotations

import json
import os as _os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest
from lumio_wiki import cli
from lumio_wiki.source_references import (
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)

ROOT = Path(__file__).parents[3]
FIXTURES = ROOT / "tests" / "fixtures"

obstore = pytest.importorskip("obstore", reason="obstore required for S3-compatible integration")
pytest.importorskip("lumio_lancedb", reason="lumio-lancedb required for the CLI binding journey")

# Skip the whole module unless an S3-compatible endpoint is configured.
if not _os.environ.get("LUMIO_S3_ENDPOINT"):  # pragma: no cover
    pytest.skip(
        "LUMIO_S3_ENDPOINT not set; skipping CLI remote LanceDB S3-compatible tests",
        allow_module_level=True,
    )


def _s3_config():
    region = _os.environ.get("LUMIO_S3_REGION", "us-east-1")
    endpoint = _os.environ["LUMIO_S3_ENDPOINT"]
    config = {
        "aws_region": region,
        "aws_endpoint": endpoint,
        "aws_access_key_id": _os.environ["LUMIO_S3_ACCESS_KEY_ID"],
        "aws_secret_access_key": _os.environ["LUMIO_S3_SECRET_ACCESS_KEY"],
    }
    client_options: dict[str, object] = {}
    if endpoint.startswith("http://"):
        client_options["allow_http"] = True
    # LanceDB storage options from the same credentials/region/endpoint
    # configuration as the canonical reads (issue #162, ADR-0013).
    storage_options = {
        "region": region,
        "endpoint": endpoint,
        "access_key_id": _os.environ["LUMIO_S3_ACCESS_KEY_ID"],
        "secret_access_key": _os.environ["LUMIO_S3_SECRET_ACCESS_KEY"],
    }
    if endpoint.startswith("http://"):
        storage_options["allow_http"] = "true"
    return config, client_options, storage_options


def _bucket() -> str:
    return _os.environ.get("LUMIO_S3_TEST_BUCKET", "lumio-wiki-it")


@pytest.fixture(scope="module")
def s3_compat_env():
    config, client_options, storage_options = _s3_config()
    bucket = _bucket()
    store = obstore.store.from_url(f"s3://{bucket}", config=config, client_options=client_options)
    yield store, bucket, storage_options
    # Best-effort cleanup of this run's objects.
    try:  # pragma: no cover - cleanup is best-effort
        for run in _RUN_PREFIXES:
            for batch in obstore.list(store, prefix=run):
                for obj in batch:
                    obstore.delete(store, obj["path"])
    except Exception:  # pragma: no cover
        pass


_RUN_PREFIXES: list[str] = []


def _publish(monkeypatch, capsys, bucket, prefix: str, *, with_lance: bool):
    """Publish one disposable Git revision through the actual CLI admission gate."""
    with tempfile.TemporaryDirectory() as temp_dir:
        source = Path(temp_dir) / "kb"
        shutil.copytree(FIXTURES / "valid", source)
        (source / ".lumio-authoring.yaml").write_bytes(
            serialize_source_reference_manifest(
                SourceReferenceManifest(
                    version=1,
                    namespace="urn:uuid:0f6f0e3e-1d9a-4b2e-9d47-6c1f0f5f4f3e",
                )
            )
        )
        subprocess.run(["git", "-C", str(source), "init", "-q"], check=True)
        subprocess.run(
            ["git", "-C", str(source), "config", "user.email", "test@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(source), "config", "user.name", "Test Author"],
            check=True,
        )
        subprocess.run(["git", "-C", str(source), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(source), "commit", "-qm", "S3 candidate"], check=True)
        revision = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        registry = Path(temp_dir) / "source-registry"
        monkeypatch.setenv("LUMIO_SOURCE_STORE", str(Path(temp_dir) / "source-store"))
        monkeypatch.delenv("LUMIO_ARTIFACT_RETENTION", raising=False)
        args = [
            "publish-s3",
            str(source),
            f"s3://{bucket}/{prefix}",
            "--revision",
            revision,
            "--expected-current",
            "none",
            "--source-registry",
            str(registry),
            "--json",
        ]
        if with_lance:
            args.extend(["--retrieval", "lancedb"])
        assert cli.main(args) == 0
        review = json.loads(capsys.readouterr().out)
        rc = cli.main([*args, "--confirm", review["review_digest"]])
        confirmed = capsys.readouterr()
        assert rc == 0, confirmed.err
        return json.loads(confirmed.out)


def _run_search(monkeypatch, bucket: str, prefix: str, query: str) -> int:
    """Run the real CLI search over the S3 URI with the lancedb backend configured."""
    monkeypatch.setenv("LUMIO_RETRIEVAL_BACKEND", "lancedb")
    rc = cli.main(["search", f"s3://{bucket}/{prefix}", query])
    assert rc == 0
    return rc


def test_cli_search_uses_published_remote_lancedb(monkeypatch, capsys, s3_compat_env):
    """Positive journey: BM25 lexical search over the published remote index."""
    _store, bucket, _storage_options = s3_compat_env
    run_prefix = f"s3-it/{uuid.uuid4().hex}"
    _RUN_PREFIXES.append(run_prefix)
    receipt = _publish(monkeypatch, capsys, bucket, run_prefix, with_lance=True)

    rc = _run_search(monkeypatch, bucket, run_prefix, "architecture")
    assert rc == 0
    out = capsys.readouterr().out
    assert "## Architecture" in out
    assert "architecture.md" in out
    # Healthy path: no fallback disclosure.
    assert "note:" not in out
    # The published version is the one that was resolved.
    assert len(receipt["version"]) == 40


def test_cli_search_falls_back_when_no_index_was_published(monkeypatch, capsys, s3_compat_env):
    """Missing remote index: truthful zero-index fallback with a disclosed note."""
    _store, bucket, _storage_options = s3_compat_env
    run_prefix = f"s3-it/{uuid.uuid4().hex}"
    _RUN_PREFIXES.append(run_prefix)
    _publish(monkeypatch, capsys, bucket, run_prefix, with_lance=False)

    rc = _run_search(monkeypatch, bucket, run_prefix, "architecture")
    assert rc == 0
    out = capsys.readouterr().out
    assert "## Architecture" in out  # zero-index results still served
    assert "note:" in out and "missing" in out and "zero-index" in out


def test_cli_search_falls_back_on_fingerprint_mismatch(monkeypatch, capsys, s3_compat_env):
    """A stale (tampered) fingerprint sidecar is rejected and disclosed."""
    import msgspec
    from lumio_wiki.fingerprint_store import FINGERPRINT_FILE
    from lumio_wiki.records import SourceFingerprint

    store, bucket, _storage_options = s3_compat_env
    run_prefix = f"s3-it/{uuid.uuid4().hex}"
    _RUN_PREFIXES.append(run_prefix)
    receipt = _publish(monkeypatch, capsys, bucket, run_prefix, with_lance=True)
    # Fault injection: overwrite the freshness sidecar with a foreign
    # fingerprint (fault injection mirrors the S3 contract suite's pattern).
    sidecar_key = f"{run_prefix}/{receipt['version']}/derived/lance/{FINGERPRINT_FILE}"
    obstore.put(store, sidecar_key, msgspec.json.encode(SourceFingerprint(digest="e" * 64)))

    rc = _run_search(monkeypatch, bucket, run_prefix, "architecture")
    assert rc == 0
    out = capsys.readouterr().out
    assert "## Architecture" in out
    assert "note:" in out and "stale" in out and "fingerprint mismatch" in out


# ---------------------------------------------------------------------------
# status — effective configuration + runtime state (issue #175).
# ---------------------------------------------------------------------------


def test_cli_status_reader_journey_with_lancedb(monkeypatch, capsys, s3_compat_env):
    """status explains a read-only S3 project: version, fingerprint, healthy lance."""
    _store, bucket, _storage_options = s3_compat_env
    run_prefix = f"s3-it/{uuid.uuid4().hex}"
    _RUN_PREFIXES.append(run_prefix)
    receipt = _publish(monkeypatch, capsys, bucket, run_prefix, with_lance=True)

    monkeypatch.setenv("LUMIO_RETRIEVAL_BACKEND", "lancedb")
    monkeypatch.setenv("LUMIO_RETRIEVAL_MODE", "hybrid")

    # Machine-readable assertions through the stable --json form.
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cli.main(["status", f"s3://{bucket}/{run_prefix}", "--json"]) == 0
    payload = json.loads(buf.getvalue())
    assert payload["role"] == "reader"
    assert payload["config_source"] == "argument"
    assert payload["published_version"] == receipt["version"]
    assert payload["fingerprint"] == receipt["fingerprint"]
    assert payload["retrieval_backend"] == "lancedb"
    assert payload["retrieval_mode"] == "hybrid"
    assert payload["lancedb_requested"] is True
    assert payload["lancedb_healthy"] is True
    assert payload["lancedb_fingerprint_matches"] is True
    assert payload["validation_valid"] is True


def test_cli_status_reader_falls_back_when_no_index_was_published(
    monkeypatch, capsys, s3_compat_env
):
    """A version published without lance: status reports the truthful fallback."""
    _store, bucket, _storage_options = s3_compat_env
    run_prefix = f"s3-it/{uuid.uuid4().hex}"
    _RUN_PREFIXES.append(run_prefix)
    _publish(monkeypatch, capsys, bucket, run_prefix, with_lance=False)

    monkeypatch.setenv("LUMIO_RETRIEVAL_BACKEND", "lancedb")
    assert cli.main(["status", f"s3://{bucket}/{run_prefix}"]) == 0
    out = capsys.readouterr().out
    assert "role:                reader (read-only S3)".replace(" ", "") in out.replace(" ", "")
    assert "reader" in out and "read-only S3" in out
    assert "lancedb_healthy" in out
    assert "false" in out
    assert "missing" in out and "zero-index" in out
    assert "publish --revision <commit>" in out
    assert "--expected-current <version|none> --retrieval lancedb" in out
