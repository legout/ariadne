"""S3-compatible integration coverage for the private Source Exchange (J4/V4).

Proves the real-endpoint transport contract (spec 0010 §6 revision 4) for
BOTH artifact kinds against the designated disposable service: interrupted
upload before readiness, maintainer download refusal before the completion
record, lost-response and retry convergence, strict download verification,
real imports through the existing J0/J3 importers (including their cross-kind
refusal), same-ID/different-bytes conflict preservation, denied-role access,
conditional-copy capability mapping and staging/endpoint/secret disclosure
boundaries. Expected values come from authored fixture bytes, public export
facts, independent ``hashlib`` digests and native Git/manifest state — never
from copied implementation output.

Skips the whole module unless the designated S3-compatible endpoint and the
three role credential pairs are configured (the existing optional-suite
convention). In the designated V4 run every variable is set; a skip there is
not evidence. Test-owned objects stay under the allocated prefix for parent
cleanup; nothing is deleted remotely.
"""

from __future__ import annotations

import hashlib
import io
import json
import os as _os
import re
import subprocess
import tarfile
from pathlib import Path

import pytest  # type: ignore[import-not-found]

obstore = pytest.importorskip("obstore", reason="obstore required for S3-compatible integration")

from lumio_wiki.artifact_store import (  # noqa: E402
    LocalDirectoryArtifactStore,
    retain_artifact,
)
from lumio_wiki.cli import main  # noqa: E402
from lumio_wiki.env_loader import SOURCE_EXCHANGE_ENV_VAR  # noqa: E402
from lumio_wiki.private_profile import ResolvedS3Exchange  # noqa: E402
from lumio_wiki.source_exchange import (  # noqa: E402
    SourceExchangeError,
    SourceTransfer,
    download_source_transfer,
    upload_source_transfer,
)
from lumio_wiki.source_handoff import (  # noqa: E402
    SourceHandoffError,
    export_source_baseline,
    export_source_handoff,
    import_source_baseline,
    import_source_handoff,
    inspect_source_baseline,
    inspect_source_handoff,
)
from lumio_wiki.source_references import (  # noqa: E402
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)
from lumio_wiki.source_registry import SourceRegistry  # noqa: E402

_ENDPOINT = _os.environ.get("LUMIO_S3_ENDPOINT", "")
_BUCKET = _os.environ.get("LUMIO_S3_TEST_BUCKET", "")
_PREFIX = _os.environ.get("LUMIO_S3_TEST_EXCHANGE_PREFIX", "")

_ROLE_VARS = {
    role: (
        f"LUMIO_S3_TEST_{role.upper()}_ACCESS_KEY_ID",
        f"LUMIO_S3_TEST_{role.upper()}_SECRET_ACCESS_KEY",
    )
    for role in ("contributor", "maintainer", "denied")
}
_REQUIRED_VARS = (
    ("LUMIO_S3_ENDPOINT", _ENDPOINT),
    ("LUMIO_S3_TEST_BUCKET", _BUCKET),
    ("LUMIO_S3_TEST_EXCHANGE_PREFIX", _PREFIX),
    ("LUMIO_S3_ACCESS_KEY_ID", _os.environ.get("LUMIO_S3_ACCESS_KEY_ID", "")),
    ("LUMIO_S3_SECRET_ACCESS_KEY", _os.environ.get("LUMIO_S3_SECRET_ACCESS_KEY", "")),
    *((name, _os.environ.get(name, "")) for pair in _ROLE_VARS.values() for name in pair),
)
_MISSING = [name for name, value in _REQUIRED_VARS if not value]
if _MISSING:  # pragma: no cover - the designated V4 run sets every variable
    pytest.skip(
        "S3-compatible exchange variables not set (" + ", ".join(_MISSING) + "); "
        "skipping Source Exchange S3-compatible tests",
        allow_module_level=True,
    )

# Secret values for disclosure assertions only (never printed).
_SECRET_MARKERS = [
    _os.environ[name] for pair in _ROLE_VARS.values() for name in pair if _os.environ.get(name)
] + [_os.environ.get("LUMIO_S3_SECRET_ACCESS_KEY", "")]

NAMESPACE = "urn:uuid:8f2f6c2e-3b1d-4e6a-9c21-7d0e5a4b1c02"
ORIGIN_CREATED_AT = "2026-10-01T09:15:00+00:00"

MANUAL_ID = "operator-manual"
MEMO_ID = "maintenance-memo"
BIG_ID = "big-report"
PRESS_ENTITY = "entity:hydraulic-press"
NOTE_ENTITY = "entity:service-memo"
BIG_ENTITY = "entity:big-report"

MANUAL_BYTES = b"Operate the hydraulic press only after the safety guard is locked."
MEMO_BYTES = b"Shift memo: replace the coolant filter weekly, Sundays before startup."
MANUAL_DIGEST = hashlib.sha256(MANUAL_BYTES).hexdigest()
MEMO_DIGEST = hashlib.sha256(MEMO_BYTES).hexdigest()

# A deterministic >5 MiB original (96 x 64 KiB sha256-chained units) proving
# the multipart streaming route; hand-authored formula, not service output.
_BIG_UNIT = b"".join(hashlib.sha256(b"j4-big|%d" % index).digest() for index in range(2048))
BIG_BYTES = _BIG_UNIT * 96
BIG_DIGEST = hashlib.sha256(BIG_BYTES).hexdigest()
assert len(BIG_BYTES) == 6 * 1024 * 1024

OTHER_BYTES = b"Conflicting replacement bytes under the same transfer identity."
OTHER_DIGEST = hashlib.sha256(OTHER_BYTES).hexdigest()

CONTROL = """\
version: 2
mode: "categorized"
categories:
  - name: concepts
ontology:
  entity_types:
    machine:
      description: "A machine documented by an original source."
    note: {}
  predicates:
    documented-at:
      subject_types:
        - machine
        - note
      literal_kind: string
"""


def _managed_page(title: str, entity_id: str, entity_type: str, source_id: str) -> str:
    # The accepted fixture page shape (KB-global claim id, no relationships
    # frontmatter, evidence-bearing object claim, semantic YAML).
    return (
        "---\n"
        f'id: "{entity_id}"\n'
        f'title: "{title}"\n'
        "entity_types:\n"
        f"  - {entity_type}\n"
        "category: concepts\n"
        'type: "machine page"\n'
        'durability_rationale: "The original document permanently supports this page."\n'
        'tags:\n  - "workshop"\n'
        f'summary: "{title} summary."\n'
        'lifecycle: "draft"\n'
        'visibility: "internal"\n'
        "sources:\n"
        f'  - id: "{source_id}"\n'
        f'    title: "{title} source"\n'
        "claims:\n"
        "  - id: claim:documented\n"
        "    predicate: documented-at\n"
        '    value: "2026-10-01"\n'
        "    value_type: string\n"
        "    status: accepted\n"
        "    evidence:\n"
        '      - section: "Overview"\n'
        "synthetic: false\n"
        "---\n\n"
        f"# {title}\n\n"
        "## Overview\n\n"
        f"Supported by the {source_id} original.\n"
    )


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if result.returncode != 0:
        raise AssertionError(f"git {args} failed: {result.stderr.decode()}")
    return result.stdout.decode().strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test Author")
    return path


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _write_manifest(kb: Path, bindings: dict, sources: dict) -> None:
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        serialize_source_reference_manifest(
            SourceReferenceManifest(
                version=1,
                namespace=NAMESPACE,
                sources=sources,
                bindings=bindings,
            )
        )
    )


def _write_base_kb(repo: Path) -> Path:
    kb = repo / "kb"
    (kb / "concepts").mkdir(parents=True)
    (kb / "lumio.yaml").write_text(CONTROL)
    (kb / "concepts" / "hydraulic-press.md").write_text(
        _managed_page("Hydraulic Press", PRESS_ENTITY, "machine", MANUAL_ID)
    )
    (kb / "concepts" / "service-memo.md").write_text(
        _managed_page("Service Memo", NOTE_ENTITY, "note", MEMO_ID)
    )
    _write_manifest(
        kb,
        bindings={PRESS_ENTITY: {MANUAL_ID: MANUAL_DIGEST}, NOTE_ENTITY: {MEMO_ID: MEMO_DIGEST}},
        sources={MANUAL_ID: "active", MEMO_ID: "active"},
    )
    return kb


def _baseline_world(tmp_path: Path):
    """A maintainer base with its registry; exports one baseline snapshot."""
    repo = _init_repo(tmp_path / "maintainer" / "repo")
    kb = _write_base_kb(repo)
    base = _commit(repo, "baseline revision")
    registry = SourceRegistry(tmp_path / "maintainer" / "registry")
    registry.register_version(
        MANUAL_ID, MANUAL_BYTES, filename="manual.pdf", content_type="application/pdf"
    )
    registry.register_version(MEMO_ID, MEMO_BYTES)
    registry.register_version("internal-note", b"never transferred")
    snapshot = tmp_path / "transfer" / "baseline.tar"
    export_source_baseline(kb, base, source_registry=registry, output_path=snapshot)
    return {"repo": repo, "kb": kb, "base": base, "snapshot": snapshot}


def _handoff_world(tmp_path: Path):
    """A contributor base+contribution adding one >5 MiB retained source."""
    repo = _init_repo(tmp_path / "contributor" / "repo")
    kb = _write_base_kb(repo)
    base = _commit(repo, "baseline revision")
    (kb / "concepts" / "big_report.md").write_text(
        _managed_page("Big Report", BIG_ENTITY, "machine", BIG_ID)
    )
    _write_manifest(
        kb,
        bindings={
            PRESS_ENTITY: {MANUAL_ID: MANUAL_DIGEST},
            NOTE_ENTITY: {MEMO_ID: MEMO_DIGEST},
            BIG_ENTITY: {BIG_ID: BIG_DIGEST},
        },
        sources={MANUAL_ID: "active", MEMO_ID: "active", BIG_ID: "active"},
    )
    contribution = _commit(repo, "contribution revision")
    registry = SourceRegistry(tmp_path / "contributor" / "registry")
    registry.register_version(
        BIG_ID, BIG_BYTES, filename="big-report.bin", content_type="application/octet-stream"
    )
    store_dir = tmp_path / "contributor" / "store"
    store_dir.mkdir(parents=True)
    store = LocalDirectoryArtifactStore(store_dir)
    retain_artifact(
        store,
        registry,
        source_id=BIG_ID,
        raw_bytes=BIG_BYTES,
        content_type="application/octet-stream",
        filename="big-report.bin",
    )
    bundle = tmp_path / "transfer" / "handoff.tar"
    export_source_handoff(
        kb,
        base,
        contribution,
        source_registry=registry,
        artifact_store=store,
        output_path=bundle,
    )
    # A separate maintainer environment for the receiving import.
    clone = tmp_path / "maintainer" / "clone"
    subprocess.run(["git", "clone", "-q", str(repo), str(clone)], capture_output=True, check=True)
    mreg_dir = tmp_path / "maintainer" / "registry"
    mstore_dir = tmp_path / "maintainer" / "store"
    mstore_dir.mkdir(parents=True)
    return {
        "repo": repo,
        "kb": kb,
        "base": base,
        "contribution": contribution,
        "bundle": bundle,
        "clone": clone,
        "clone_kb": clone / "kb",
        "registry_dir": mreg_dir,
        "store": LocalDirectoryArtifactStore(mstore_dir),
    }


def _manifest_of(archive: Path) -> dict:
    with tarfile.open(archive, "r:") as tar:
        stream = tar.extractfile("manifest.json")
        assert stream is not None
        return json.loads(stream.read())


def _role_store(role: str):
    access_var, secret_var = _ROLE_VARS[role]
    config = {
        "aws_endpoint_url_s3": _ENDPOINT,
        "aws_endpoint": _ENDPOINT,
        "aws_region": _os.environ.get("LUMIO_S3_REGION", "us-east-1"),
        "aws_virtual_hosted_style_request": False,
        "aws_skip_signature": False,
        "copy_if_not_exists": "multipart",
        "aws_access_key_id": _os.environ[access_var],
        "aws_secret_access_key": _os.environ[secret_var],
    }
    client_options = {"allow_http": True} if _ENDPOINT.startswith("http://") else None
    return obstore.store.S3Store(_BUCKET, config=config, client_options=client_options)


def _exchange(role: str) -> ResolvedS3Exchange:
    return ResolvedS3Exchange(store=_role_store(role), prefix=_PREFIX)


def _raw_key(transfer_id: str, member: str) -> str:
    return f"{_PREFIX}/{transfer_id}/{member}"


def _remote_digest(store, key: str) -> tuple[str, int]:
    result = obstore.get(store, key)
    hasher = hashlib.sha256()
    total = 0
    for buf in result.stream():
        hasher.update(buf)
        total += len(buf)
    return hasher.hexdigest(), total


def _assert_no_disclosure(text: str) -> None:
    assert _ENDPOINT not in text, "endpoint leaked"
    assert _BUCKET not in text, "bucket leaked"
    assert _PREFIX not in text, "prefix leaked"
    assert "_staging" not in text, "staging key leaked"
    for marker in _SECRET_MARKERS:
        if marker:
            assert marker not in text, "credential material leaked"


def _interrupted_ready_put():
    """Wrap obstore.put: the ready.json write is interrupted BEFORE performing."""
    real_put = obstore.put

    def wrapped(store, path, *args, **kwargs):
        if str(path).endswith("/ready.json"):
            raise RuntimeError("injected interruption before ready publication")
        return real_put(store, path, *args, **kwargs)

    return real_put, wrapped


def _lost_copy_response():
    """Wrap obstore.copy: the copy lands (or already landed on retry), then the
    response is lost — forcing recovery by remote verification."""
    from obstore.exceptions import AlreadyExistsError

    real_copy = obstore.copy

    def wrapped(store, from_, to, *args, **kwargs):
        try:
            real_copy(store, from_, to, *args, **kwargs)
        except AlreadyExistsError:
            pass  # the interrupted attempt already landed the final object
        raise RuntimeError("injected lost copy response")

    return real_copy, wrapped


def _craft_archive(
    path: Path, manifest: dict, entries: list[tuple[str, bytes]] | None = None
) -> str:
    """Hand-build one v1 archive from the documented container contract."""
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _info(name: str, size: int) -> tarfile.TarInfo:
        info = tarfile.TarInfo(name)
        info.size = size
        info.mode = 0o644
        info.uid = 0
        info.gid = 0
        info.uname = ""
        info.gname = ""
        info.mtime = 0
        info.type = tarfile.REGTYPE
        return info

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        tar.addfile(_info("manifest.json", len(payload)), io.BytesIO(payload))
        for name, data in entries or []:
            tar.addfile(_info(name, len(data)), io.BytesIO(data))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buffer.getvalue())
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def _expected_transfer(kind: str, operation: str, archive: Path) -> dict:
    """Independent expectations from the authored artifact bytes."""
    manifest = _manifest_of(archive)
    return {
        "schema_version": 1,
        "operation": operation,
        "kind": kind,
        "transfer_id": manifest["transfer_id"],
        "byte_count": archive.stat().st_size,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    }


@pytest.mark.parametrize("kind", ["source-baseline", "source-handoff"])
def test_exchange_completion_and_retry(kind, tmp_path, monkeypatch):
    world = _baseline_world(tmp_path) if kind == "source-baseline" else _handoff_world(tmp_path)
    artifact = world["snapshot"] if kind == "source-baseline" else world["bundle"]
    expected = _expected_transfer(kind, "upload", artifact)
    transfer_id = expected["transfer_id"]
    digest = expected["sha256"]
    byte_count = expected["byte_count"]
    if kind == "source-handoff":
        # The named >5 MiB full-source route through multipart streaming.
        assert byte_count > 5 * 1024 * 1024

    contributor = _exchange("contributor")
    maintainer = _exchange("maintainer")
    denied = _exchange("denied")

    # (1) Interrupted upload BEFORE ready publication: real final bytes land,
    # readiness is never advertised, and the failure is safe.
    real_put, wrapped_put = _interrupted_ready_put()
    obstore.put = wrapped_put
    try:
        with pytest.raises(SourceExchangeError) as interrupted:
            upload_source_transfer(artifact, exchange=contributor)
    finally:
        obstore.put = real_put
    assert interrupted.value.code == "invalid_source_exchange"
    _assert_no_disclosure(str(interrupted.value))
    maintainer_raw = _role_store("maintainer")
    meta = obstore.head(maintainer_raw, _raw_key(transfer_id, "transfer.tar"))
    assert meta["size"] == byte_count  # actual remote final bytes present
    with pytest.raises(FileNotFoundError):
        obstore.head(maintainer_raw, _raw_key(transfer_id, "ready.json"))
    staging = [
        obj["path"]
        for batch in obstore.list(maintainer_raw, prefix=f"{_PREFIX}/_staging/")
        for obj in batch
    ]
    assert staging, "interrupted upload must leave operator-controlled staging residue"
    for path in staging:
        assert path.startswith(f"{_PREFIX}/_staging/")

    # (2) A maintainer cannot download before the completion record exists.
    output = tmp_path / "download" / f"{kind}.tar"
    output.parent.mkdir(parents=True)
    with pytest.raises(SourceExchangeError) as refused:
        download_source_transfer(transfer_id, digest, exchange=maintainer, output_path=output)
    assert refused.value.code == "exchange_not_found"
    _assert_no_disclosure(str(refused.value))
    assert not output.exists()  # no partial or unverified output

    # (3) Retry with a LOST copy response converges: the remote outcome is
    # verified, readiness is published, and the result matches authored facts.
    real_copy, wrapped_copy = _lost_copy_response()
    obstore.copy = wrapped_copy
    try:
        uploaded = upload_source_transfer(artifact, exchange=contributor)
    finally:
        obstore.copy = real_copy
    assert uploaded == SourceTransfer(
        schema_version=1,
        operation="upload",
        kind=kind,
        transfer_id=transfer_id,
        byte_count=byte_count,
        sha256=digest,
    )
    _assert_no_disclosure(str(uploaded))
    ready = json.loads(
        bytes(obstore.get(maintainer_raw, _raw_key(transfer_id, "ready.json")).bytes())
    )
    assert ready == {
        "schema_version": 1,
        "kind": kind,
        "transfer_id": transfer_id,
        "byte_count": byte_count,
        "sha256": digest,
    }

    # (4) An identical retry after success converges without conflict.
    again = upload_source_transfer(artifact, exchange=contributor)
    assert again == uploaded

    # (5) Verified download exposing only fully validated bytes.
    downloaded = download_source_transfer(
        transfer_id, digest, exchange=maintainer, output_path=output
    )
    assert downloaded == SourceTransfer(
        schema_version=1,
        operation="download",
        kind=kind,
        transfer_id=transfer_id,
        byte_count=byte_count,
        sha256=digest,
    )
    assert hashlib.sha256(output.read_bytes()).hexdigest() == digest
    assert output.read_bytes() == artifact.read_bytes()

    # (6) The downloaded artifact feeds the EXISTING importers (never a second
    # importer at the transport layer), plus the baseline-vs-full refusal.
    if kind == "source-baseline":
        clone = tmp_path / "contributor" / "clone"
        subprocess.run(
            ["git", "clone", "-q", str(world["repo"]), str(clone)],
            capture_output=True,
            check=True,
        )
        creg = SourceRegistry(tmp_path / "contributor" / "registry")
        preview = inspect_source_baseline(
            clone / "kb",
            output,
            world["base"],
            expected_digest=digest,
            source_registry=creg,
        )
        assert preview.ready
        imported = import_source_baseline(
            clone / "kb",
            output,
            world["base"],
            expected_digest=digest,
            source_registry=creg,
            confirmation=preview.confirmation_digest,
        )
        assert imported.status == "imported"
        assert imported.versions_added == 2  # authored fact: manual + memo
        assert imported.versions_reused == 0
        with pytest.raises(SourceHandoffError):  # cross-kind importer refusal
            inspect_source_handoff(
                clone / "kb",
                output,
                world["base"],
                expected_digest=digest,
                source_registry=creg,
                artifact_store=LocalDirectoryArtifactStore(tmp_path / "contributor" / "store"),
            )
    else:
        mreg = SourceRegistry(world["registry_dir"])
        preview = inspect_source_handoff(
            world["clone_kb"],
            output,
            world["contribution"],
            expected_digest=digest,
            source_registry=mreg,
            artifact_store=world["store"],
        )
        assert preview.ready
        imported = import_source_handoff(
            world["clone_kb"],
            output,
            world["contribution"],
            expected_digest=digest,
            source_registry=mreg,
            artifact_store=world["store"],
            confirmation=preview.confirmation_digest,
        )
        assert imported.status == "imported"
        assert imported.versions_added == 1  # authored fact: the big source
        assert imported.artifacts_retained == 1
        assert world["store"].get_artifact(source_id=BIG_ID, content_hash=BIG_DIGEST) == BIG_BYTES

    # (7) The denied role never reads the transfer.
    denied_output = tmp_path / "download" / "denied.tar"
    with pytest.raises(SourceExchangeError) as denied_error:
        download_source_transfer(transfer_id, digest, exchange=denied, output_path=denied_output)
    assert denied_error.value.code == "exchange_access_denied"
    _assert_no_disclosure(str(denied_error.value))
    assert not denied_output.exists()


def _conflicting_archive(kind: str, real_manifest: dict, path: Path) -> str:
    """A VALID v1 archive of the same kind carrying the SAME transfer id but
    different bytes (authored from the documented contract, not exporter output)."""
    manifest = json.loads(json.dumps(real_manifest))  # deep copy
    if kind == "source-baseline":
        for version in manifest["versions"]:
            if version["source_id"] == MANUAL_ID:
                version["content_hash"] = OTHER_DIGEST
                version["size"] = len(OTHER_BYTES)
                version["filename"] = "other.pdf"
        for binding in manifest["bindings"]:
            if binding["source_id"] == MANUAL_ID:
                binding["content_hash"] = OTHER_DIGEST
        return _craft_archive(path, manifest)
    manifest["bindings"] = []
    first = json.loads(json.dumps(real_manifest["versions"][0]))
    first["content_hash"] = OTHER_DIGEST
    first["size"] = len(OTHER_BYTES)
    # No binding selects this version, so J3's accepted justification rule
    # requires the supplementary-reference intent for structural validity.
    first["intent"] = "reuse"
    manifest["versions"] = [first]
    return _craft_archive(path, manifest, entries=[(f"artifacts/{OTHER_DIGEST}", OTHER_BYTES)])


@pytest.mark.parametrize("kind", ["source-baseline", "source-handoff"])
def test_exchange_same_id_different_bytes_conflict(kind, tmp_path):
    world = _baseline_world(tmp_path) if kind == "source-baseline" else _handoff_world(tmp_path)
    artifact = world["snapshot"] if kind == "source-baseline" else world["bundle"]
    expected = _expected_transfer(kind, "upload", artifact)
    transfer_id = expected["transfer_id"]
    original_digest = expected["sha256"]

    contributor = _exchange("contributor")
    upload_source_transfer(artifact, exchange=contributor)

    conflicting = tmp_path / "transfer" / f"conflicting-{kind}.tar"
    _conflicting_archive(kind, _manifest_of(artifact), conflicting)
    assert hashlib.sha256(conflicting.read_bytes()).hexdigest() != original_digest
    with pytest.raises(SourceExchangeError) as conflict:
        upload_source_transfer(conflicting, exchange=contributor)
    assert conflict.value.code == "exchange_conflict"
    _assert_no_disclosure(str(conflict.value))

    maintainer_raw = _role_store("maintainer")
    remote_digest, remote_total = _remote_digest(
        maintainer_raw, _raw_key(transfer_id, "transfer.tar")
    )
    assert remote_digest == original_digest  # final bytes preserved
    assert remote_total == expected["byte_count"]
    ready = json.loads(
        bytes(obstore.get(maintainer_raw, _raw_key(transfer_id, "ready.json")).bytes())
    )
    assert ready["sha256"] == original_digest  # readiness still names the original


@pytest.mark.parametrize(
    "variant",
    [
        "unknown_field",
        "wrong_sha",
        "wrong_kind",
        "wrong_id",
        "oversized",
        "mismatched_caller_digest",
        "swapped_final_archive",
    ],
)
def test_exchange_invalid_ready_refuses_before_output(variant, tmp_path):
    world = _baseline_world(tmp_path)
    artifact = world["snapshot"]
    facts = _expected_transfer("source-baseline", "upload", artifact)
    transfer_id = facts["transfer_id"]
    digest = facts["sha256"]

    # Baseline export of identical captured facts is deterministic — the
    # transfer id is content-derived — so a second export does NOT yield a
    # fresh id or different bytes. 'other' is therefore hand-authored from
    # the documented v1 baseline contract with distinct authored facts
    # (manifest-only: a baseline archive carries no artifact entry).
    other_manifest = {
        "schema_version": 1,
        "kind": "source-baseline",
        "transfer_id": "c" * 64,
        "namespace": NAMESPACE,
        "kb_subtree": "kb",
        "revision": world["base"],
        "source_manifest_digest": _manifest_of(artifact)["source_manifest_digest"],
        "bindings": [
            {
                "entity_id": PRESS_ENTITY,
                "source_id": MANUAL_ID,
                "content_hash": OTHER_DIGEST,
            }
        ],
        "versions": [
            {
                "source_id": MANUAL_ID,
                "content_hash": OTHER_DIGEST,
                "size": len(OTHER_BYTES),
                "content_type": "application/pdf",
                "filename": "other.pdf",
                "origin_created_at": ORIGIN_CREATED_AT,
            }
        ],
    }
    other = tmp_path / "transfer" / "other.tar"
    other_digest = _craft_archive(other, other_manifest)
    other_id = other_manifest["transfer_id"]
    other_byte_count = other.stat().st_size
    # Authored-fact guards (not implementation output): the id, the complete
    # archive digest and the source digest all actually differ from the
    # original, and binding/version facts stay consistent. (Padded tar
    # lengths may legitimately be equal: differently valued manifests can
    # share one RECORDSIZE-padded archive length.)
    assert other_id != transfer_id and re.fullmatch(r"[0-9a-f]{64}", other_id)
    assert other_digest != digest
    assert OTHER_DIGEST not in {MANUAL_DIGEST, MEMO_DIGEST}
    assert other_manifest["bindings"][0]["content_hash"] == OTHER_DIGEST
    assert other_manifest["versions"][0]["content_hash"] == OTHER_DIGEST
    assert other_manifest["versions"][0]["size"] == len(OTHER_BYTES)

    # Hand-craft the remote state (test-owned objects; no deletes).
    raw = _role_store("contributor")
    final_bytes = (
        other.read_bytes() if variant == "swapped_final_archive" else artifact.read_bytes()
    )
    obstore.put(raw, _raw_key(transfer_id, "transfer.tar"), final_bytes)
    ready: dict = {
        "schema_version": 1,
        "kind": "source-baseline",
        "transfer_id": transfer_id,
        "byte_count": facts["byte_count"],
        "sha256": digest,
    }
    caller_digest = digest
    if variant == "unknown_field":
        ready["extra"] = "field"
    elif variant == "wrong_sha":
        ready["sha256"] = other_digest
    elif variant == "wrong_kind":
        ready["kind"] = "source-handoff"
    elif variant == "wrong_id":
        ready["transfer_id"] = other_id
    elif variant == "oversized":
        ready["padding"] = "x" * (80 * 1024)
    elif variant == "mismatched_caller_digest":
        caller_digest = other_digest
    elif variant == "swapped_final_archive":
        ready["sha256"] = other_digest
        ready["byte_count"] = other_byte_count
        caller_digest = other_digest
    obstore.put(raw, _raw_key(transfer_id, "ready.json"), json.dumps(ready).encode())

    output = tmp_path / "download" / f"{variant}.tar"
    output.parent.mkdir(parents=True)
    with pytest.raises(SourceExchangeError) as refused:
        download_source_transfer(
            transfer_id, caller_digest, exchange=_exchange("maintainer"), output_path=output
        )
    assert refused.value.code == "exchange_integrity_mismatch"
    _assert_no_disclosure(str(refused.value))
    assert not output.exists()  # failures never expose partial/unverified output
    assert list(output.parent.iterdir()) == []  # no stray temporaries


def test_exchange_unsupported_conditional_capability(tmp_path):
    from obstore.exceptions import NotSupportedError

    class _InjectedUnsupported(NotSupportedError):
        pass

    world = _baseline_world(tmp_path)
    artifact = world["snapshot"]
    facts = _expected_transfer("source-baseline", "upload", artifact)

    real_copy = obstore.copy

    def wrapped(*args, **kwargs):
        raise _InjectedUnsupported("injected capability refusal")

    obstore.copy = wrapped
    try:
        with pytest.raises(SourceExchangeError) as unsupported:
            upload_source_transfer(artifact, exchange=_exchange("contributor"))
    finally:
        obstore.copy = real_copy
    assert unsupported.value.code == "exchange_unsupported"
    assert "manual" in str(unsupported.value)  # the fallback stays available
    _assert_no_disclosure(str(unsupported.value))
    # Nothing was advertised under the identifier.
    with pytest.raises(FileNotFoundError):
        obstore.head(_role_store("maintainer"), _raw_key(facts["transfer_id"], "transfer.tar"))


def test_exchange_cli_selection_and_errors(tmp_path, capsys, monkeypatch):
    from lumio_wiki.env_loader import (
        ARTIFACT_RETENTION_ENV_VAR,
        KB_PATH_ENV_VAR,
        SOURCE_REGISTRY_ENV_VAR,
        SOURCE_STORE_ENV_VAR,
    )

    for variable in (
        SOURCE_EXCHANGE_ENV_VAR,
        SOURCE_REGISTRY_ENV_VAR,
        SOURCE_STORE_ENV_VAR,
        ARTIFACT_RETENTION_ENV_VAR,
        KB_PATH_ENV_VAR,
    ):
        monkeypatch.delenv(variable, raising=False)
    world = _baseline_world(tmp_path)
    artifact = world["snapshot"]
    facts = _expected_transfer("source-baseline", "upload", artifact)
    uri = f"s3://{_BUCKET}/{_PREFIX}"
    marker = re.fullmatch(r"[0-9a-f]{64}", facts["transfer_id"])
    assert marker is not None

    # Explicit legacy route (contributor legacy credentials from the runner).
    code = main(
        [
            "source-exchange",
            "upload",
            "--file",
            str(artifact),
            "--exchange",
            uri,
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": True, **facts}
    _assert_no_disclosure(json.dumps(payload))

    # Effective client config: an ambient S3-specific endpoint cannot hijack
    # the explicitly selected endpoint.
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", "http://127.0.0.1:9")
    downloaded = tmp_path / "cli" / "baseline.tar"
    downloaded.parent.mkdir(parents=True)
    code = main(
        [
            "source-exchange",
            "download",
            "--id",
            facts["transfer_id"],
            "--digest",
            facts["sha256"],
            "--exchange",
            uri,
            "--output",
            str(downloaded),
            "--json",
        ]
    )
    monkeypatch.delenv("AWS_ENDPOINT_URL_S3")
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["operation"] == "download"
    assert hashlib.sha256(downloaded.read_bytes()).hexdigest() == facts["sha256"]
    _assert_no_disclosure(json.dumps(result))

    # Profile route: --kb is mandatory and competitors are refused.
    second = tmp_path / "transfer" / "second.tar"
    export_source_baseline(
        world["kb"],
        world["base"],
        source_registry=SourceRegistry(tmp_path / "maintainer" / "registry"),
        output_path=second,
    )
    second_facts = _expected_transfer("source-baseline", "upload", second)
    profile = tmp_path / "contributor" / "profile.json"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "namespace": NAMESPACE,
                "source_registry": str((tmp_path / "contributor" / "registry").resolve()),
                "retention": "required",
                "artifact_store": {
                    "kind": "local",
                    "root": str((tmp_path / "contributor" / "store").resolve()),
                },
                "exchange": {
                    "kind": "s3",
                    "bucket": _BUCKET,
                    "prefix": _PREFIX,
                    "endpoint": _ENDPOINT,
                    "region": _os.environ.get("LUMIO_S3_REGION", "us-east-1"),
                    "url_style": "path",
                    "credentials": {
                        "access_key_id_env": "LUMIO_S3_TEST_CONTRIBUTOR_ACCESS_KEY_ID",
                        "secret_access_key_env": "LUMIO_S3_TEST_CONTRIBUTOR_SECRET_ACCESS_KEY",
                    },
                },
            }
        )
    )
    code = main(
        [
            "source-exchange",
            "upload",
            "--file",
            str(second),
            "--private-profile",
            str(profile),
            "--json",
        ]
    )
    assert code == 2
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["schema_version"] == 1
    assert envelope["error"]["code"] == "invalid_private_profile"

    code = main(
        [
            "source-exchange",
            "upload",
            "--file",
            str(second),
            "--private-profile",
            str(profile),
            "--kb",
            str(world["kb"]),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": True, **second_facts}
    _assert_no_disclosure(json.dumps(payload))

    code = main(
        [
            "source-exchange",
            "upload",
            "--file",
            str(second),
            "--private-profile",
            str(profile),
            "--kb",
            str(world["kb"]),
            "--exchange",
            uri,
            "--json",
        ]
    )
    assert code == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "conflicting_private_selection"

    monkeypatch.setenv(SOURCE_EXCHANGE_ENV_VAR, uri)
    code = main(
        [
            "source-exchange",
            "upload",
            "--file",
            str(second),
            "--private-profile",
            str(profile),
            "--kb",
            str(world["kb"]),
            "--json",
        ]
    )
    monkeypatch.delenv(SOURCE_EXCHANGE_ENV_VAR)
    assert code == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "conflicting_private_selection"

    # No selection at all is an actionable refusal, not a guess.
    code = main(["source-exchange", "upload", "--file", str(artifact), "--json"])
    assert code == 2
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["schema_version"] == 1
    assert envelope["error"]["code"] == "invalid_source_exchange"

    # Malformed caller digest: structured, versioned, no partial output.
    bad_output = tmp_path / "cli" / "bad.tar"
    code = main(
        [
            "source-exchange",
            "download",
            "--id",
            facts["transfer_id"],
            "--digest",
            "not-a-digest",
            "--exchange",
            uri,
            "--output",
            str(bad_output),
            "--json",
        ]
    )
    assert code == 2
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["schema_version"] == 1
    assert envelope["error"]["code"] == "invalid_source_exchange"
    _assert_no_disclosure(json.dumps(envelope))
    assert not bad_output.exists()


# ---------------------------------------------------------------------------
# Review regressions F1-F7 (j4-review.md). These pin the CONTRACT the review
# found violated; against the unrepaired implementation they are expected to
# FAIL (genuine RED evidence), each at its named defect — never at unrelated
# fixture setup. Independent oracles: written plan ceilings, authored bytes,
# native filesystem/device facts, real Git worktrees and real remote objects.
# ---------------------------------------------------------------------------

# Written transfer ceilings (plan 0010 transfer bounds): a baseline container
# is bounded by the 4 MiB manifest + 1 MiB tar overhead; a full handoff by
# 4 MiB manifest + 2 GiB payload + 8 MiB overhead.
_BASELINE_CEILING = 5 * 1024 * 1024
_FULL_CEILING = (4 + 2048 + 8) * 1024 * 1024


def _craft_remote_state(raw, transfer_id: str, final_bytes: bytes, ready: dict) -> None:
    """Hand-craft real remote objects (test-owned; no deletes)."""
    obstore.put(raw, _raw_key(transfer_id, "transfer.tar"), final_bytes)
    obstore.put(raw, _raw_key(transfer_id, "ready.json"), json.dumps(ready).encode())


def _counting_archive_gets():
    """Wrap obstore.get: delegate everything, count archive-member GETs."""
    real_get = obstore.get
    counter = {"archive_gets": 0}

    def wrapped(store, path, *args, **kwargs):
        if str(path).endswith("/transfer.tar"):
            counter["archive_gets"] += 1
        return real_get(store, path, *args, **kwargs)

    return real_get, wrapped, counter


@pytest.mark.parametrize(
    ("kind", "declared_count"),
    [
        ("source-baseline", _BASELINE_CEILING + 1),
        ("source-handoff", _FULL_CEILING + 1),
    ],
)
def test_exchange_download_enforces_kind_limit(kind, declared_count, tmp_path):
    """F1: a remote-advertised count above the kind's written ceiling must be
    refused BEFORE any archive fetch or output exposure — the remote count is
    not resource authority."""
    world = _baseline_world(tmp_path)
    artifact = world["snapshot"]
    facts = _expected_transfer("source-baseline", "upload", artifact)
    # Tiny real final object; the ready record lies only about the count.
    ready = {
        "schema_version": 1,
        "kind": kind,
        "transfer_id": facts["transfer_id"],
        "byte_count": declared_count,
        "sha256": facts["sha256"],
    }
    _craft_remote_state(
        _role_store("contributor"), facts["transfer_id"], artifact.read_bytes(), ready
    )

    output = tmp_path / "download" / "over-ceiling.tar"
    output.parent.mkdir(parents=True)
    real_get, wrapped_get, counter = _counting_archive_gets()
    obstore.get = wrapped_get
    try:
        with pytest.raises(SourceExchangeError) as refused:
            download_source_transfer(
                facts["transfer_id"],
                facts["sha256"],
                exchange=_exchange("maintainer"),
                output_path=output,
            )
    finally:
        obstore.get = real_get
    assert refused.value.code == "exchange_integrity_mismatch"
    assert counter["archive_gets"] == 0, "archive fetched before ceiling refusal"
    assert not output.exists()


@pytest.mark.parametrize(
    "mutation",
    ["unhashable_kind", "malformed_remote_transfer_id", "malformed_remote_sha256"],
)
def test_exchange_ready_field_types_are_bounded(mutation, tmp_path, capsys, monkeypatch):
    """F2: wrong-type/malformed REMOTE ready fields must surface as a bounded
    exchange_integrity_mismatch on SDK and JSON CLI paths — never an uncaught
    TypeError, wrong category or traceback."""
    from lumio_wiki.env_loader import KB_PATH_ENV_VAR, SOURCE_EXCHANGE_ENV_VAR

    for variable in (SOURCE_EXCHANGE_ENV_VAR, KB_PATH_ENV_VAR):
        monkeypatch.delenv(variable, raising=False)

    world = _baseline_world(tmp_path)
    artifact = world["snapshot"]
    facts = _expected_transfer("source-baseline", "upload", artifact)
    ready = {
        "schema_version": 1,
        "kind": "source-baseline",
        "transfer_id": facts["transfer_id"],
        "byte_count": facts["byte_count"],
        "sha256": facts["sha256"],
    }
    if mutation == "unhashable_kind":
        ready["kind"] = []
    elif mutation == "malformed_remote_transfer_id":
        ready["transfer_id"] = "not-a-valid-remote-id"
    else:
        ready["sha256"] = 12345
    _craft_remote_state(
        _role_store("contributor"), facts["transfer_id"], artifact.read_bytes(), ready
    )

    output = tmp_path / "download" / f"{mutation}.tar"
    output.parent.mkdir(parents=True)
    with pytest.raises(SourceExchangeError) as refused:
        download_source_transfer(
            facts["transfer_id"],
            facts["sha256"],
            exchange=_exchange("maintainer"),
            output_path=output,
        )
    assert refused.value.code == "exchange_integrity_mismatch"
    assert not output.exists()

    cli_output = tmp_path / "download" / f"{mutation}-cli.tar"
    code = main(
        [
            "source-exchange",
            "download",
            "--id",
            facts["transfer_id"],
            "--digest",
            facts["sha256"],
            "--exchange",
            f"s3://{_BUCKET}/{_PREFIX}",
            "--output",
            str(cli_output),
            "--json",
        ]
    )
    assert code == 2
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["schema_version"] == 1
    assert envelope["error"]["code"] == "exchange_integrity_mismatch"
    _assert_no_disclosure(json.dumps(envelope))
    assert not cli_output.exists()


def _upload_baseline(tmp_path: Path):
    world = _baseline_world(tmp_path)
    artifact = world["snapshot"]
    facts = _expected_transfer("source-baseline", "upload", artifact)
    upload_source_transfer(artifact, exchange=_exchange("contributor"))
    return world, artifact, facts


def test_exchange_publication_cross_filesystem(tmp_path):
    """F3a: a verified transfer must publish onto a DIFFERENT filesystem
    (staging temp vs destination device) instead of failing EXDEV."""
    import tempfile as _tempfile

    _world, artifact, facts = _upload_baseline(tmp_path)
    with _tempfile.TemporaryDirectory(dir="/dev/shm") as shm:
        # Native device oracle: the destination filesystem genuinely differs
        # from the operation's staging temp root.
        assert _os.stat(shm).st_dev != _os.stat(_tempfile.gettempdir()).st_dev
        output = Path(shm) / "transfer.tar"
        downloaded = download_source_transfer(
            facts["transfer_id"],
            facts["sha256"],
            exchange=_exchange("maintainer"),
            output_path=output,
        )
        assert downloaded.operation == "download"
        assert output.read_bytes() == artifact.read_bytes()
        assert [p.name for p in Path(shm).iterdir()] == ["transfer.tar"]


def test_exchange_publication_no_clobber(tmp_path):
    """F3b: an unrelated destination file appearing immediately before the
    atomic publication primitive must never be silently destroyed."""
    _world, artifact, facts = _upload_baseline(tmp_path)
    output = tmp_path / "download" / "transfer.tar"
    output.parent.mkdir(parents=True)
    sentinel_bytes = b"unrelated local sentinel content never to be clobbered"
    fired: list[str] = []
    real_replace = _os.replace
    real_link = _os.link

    def _arm(destination: Path) -> None:
        if Path(destination) == output and not fired:
            output.write_bytes(sentinel_bytes)
            fired.append("armed")

    def wrapped_replace(src, dst, **kwargs):
        _arm(dst)
        return real_replace(src, dst, **kwargs)

    def wrapped_link(src, dst, **kwargs):
        _arm(dst)
        return real_link(src, dst, **kwargs)

    _os.replace = wrapped_replace
    _os.link = wrapped_link
    try:
        with pytest.raises(SourceExchangeError) as refused:
            download_source_transfer(
                facts["transfer_id"],
                facts["sha256"],
                exchange=_exchange("maintainer"),
                output_path=output,
            )
    finally:
        _os.replace = real_replace
        _os.link = real_link
    assert fired == ["armed"], "publication primitive ran without the injection firing"
    assert refused.value.code == "exchange_conflict"
    assert output.read_bytes() == sentinel_bytes  # unrelated file preserved


def _git_fixture_with_ignored_dir(tmp_path: Path) -> Path:
    repo = _init_repo(tmp_path / "content-repo")
    (repo / ".gitignore").write_text("private-ignored/\n")
    (repo / "README.md").write_text("content repository\n")
    (repo / "private-ignored").mkdir()
    _commit(repo, "content base with ignored private directory")
    return repo


def test_exchange_download_refuses_git_output_sdk(tmp_path):
    """F4a: the public SDK download must refuse to publish a private
    full-source transfer inside a Git worktree (ignored directory included)."""
    world = _handoff_world(tmp_path)
    bundle = world["bundle"]
    facts = _expected_transfer("source-handoff", "upload", bundle)
    upload_source_transfer(bundle, exchange=_exchange("contributor"))

    repo = _git_fixture_with_ignored_dir(tmp_path)
    assert (repo / ".git").exists()  # native worktree oracle
    output = repo / "private-ignored" / "transfer.tar"
    with pytest.raises(SourceExchangeError) as refused:
        download_source_transfer(
            facts["transfer_id"],
            facts["sha256"],
            exchange=_exchange("maintainer"),
            output_path=output,
        )
    _assert_no_disclosure(str(refused.value))
    assert not output.exists()
    assert _git(repo, "status", "--porcelain") == ""


def test_exchange_download_refuses_git_output_explicit_cli(tmp_path, capsys, monkeypatch):
    """F4b: the explicit --exchange CLI route (no KB) must refuse an output
    path whose parent is a SYMLINK resolving into an ignored Git directory."""
    from lumio_wiki.env_loader import KB_PATH_ENV_VAR, SOURCE_EXCHANGE_ENV_VAR

    for variable in (SOURCE_EXCHANGE_ENV_VAR, KB_PATH_ENV_VAR):
        monkeypatch.delenv(variable, raising=False)
    world = _handoff_world(tmp_path)
    bundle = world["bundle"]
    facts = _expected_transfer("source-handoff", "upload", bundle)
    upload_source_transfer(bundle, exchange=_exchange("contributor"))

    repo = _git_fixture_with_ignored_dir(tmp_path)
    link = tmp_path / "link-to-ignored"
    link.symlink_to(repo / "private-ignored")
    output = link / "transfer.tar"
    code = main(
        [
            "source-exchange",
            "download",
            "--id",
            facts["transfer_id"],
            "--digest",
            facts["sha256"],
            "--exchange",
            f"s3://{_BUCKET}/{_PREFIX}",
            "--output",
            str(output),
            "--json",
        ]
    )
    assert code == 2
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["schema_version"] == 1
    _assert_no_disclosure(json.dumps(envelope))
    assert not output.exists()
    assert not (repo / "private-ignored" / "transfer.tar").exists()
    assert _git(repo, "status", "--porcelain") == ""


def test_exchange_expected_failures_safe_missing_private_input(tmp_path, capsys, monkeypatch):
    """F5a: a missing private input path must not be echoed into SDK messages
    or ordinary CLI diagnostics."""
    from lumio_wiki.env_loader import KB_PATH_ENV_VAR, SOURCE_EXCHANGE_ENV_VAR

    for variable in (SOURCE_EXCHANGE_ENV_VAR, KB_PATH_ENV_VAR):
        monkeypatch.delenv(variable, raising=False)
    sentinel = tmp_path / "private" / "definitely-missing-sentinel-transfer.tar"
    with pytest.raises(SourceExchangeError) as refused:
        upload_source_transfer(sentinel, exchange=_exchange("contributor"))
    assert str(sentinel) not in str(refused.value)
    _assert_no_disclosure(str(refused.value))

    code = main(
        [
            "source-exchange",
            "upload",
            "--file",
            str(sentinel),
            "--exchange",
            f"s3://{_BUCKET}/{_PREFIX}",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert str(sentinel) not in captured.err + captured.out
    assert "traceback" not in (captured.err + captured.out).lower()


def test_exchange_expected_failures_safe_temp_allocation(tmp_path, capsys, monkeypatch):
    """F5b: a private temporary-allocation failure must surface as a bounded
    SourceExchangeError/CLI envelope, never a raw filesystem exception."""
    import tempfile as _tempfile

    for variable in (SOURCE_EXCHANGE_ENV_VAR,):
        monkeypatch.delenv(variable, raising=False)
    _world, artifact, _facts = _upload_baseline(tmp_path)
    second = tmp_path / "transfer" / "second.tar"
    export_source_baseline(
        _world["kb"],
        _world["base"],
        source_registry=SourceRegistry(tmp_path / "maintainer" / "registry"),
        output_path=second,
    )
    allocation_sentinel = "/private-sentinel-allocation-path"
    real_mkdtemp = _tempfile.mkdtemp

    def wrapped_mkdtemp(*args, **kwargs):
        if "lumio-source-exchange" in str(kwargs.get("prefix", "")):
            raise OSError(28, "no space left on device", allocation_sentinel)
        return real_mkdtemp(*args, **kwargs)

    monkeypatch.setattr(_tempfile, "mkdtemp", wrapped_mkdtemp)
    with pytest.raises(SourceExchangeError) as refused:
        upload_source_transfer(second, exchange=_exchange("contributor"))
    assert allocation_sentinel not in str(refused.value)
    _assert_no_disclosure(str(refused.value))

    code = main(
        [
            "source-exchange",
            "upload",
            "--file",
            str(second),
            "--exchange",
            f"s3://{_BUCKET}/{_PREFIX}",
            "--json",
        ]
    )
    monkeypatch.undo()
    envelope = json.loads(capsys.readouterr().out)
    assert code == 2
    assert envelope["schema_version"] == 1
    _assert_no_disclosure(json.dumps(envelope))
    assert allocation_sentinel not in json.dumps(envelope)


def test_exchange_expected_failures_safe_missing_s3_extra(tmp_path, capsys, monkeypatch):
    """F5c: with the optional S3 extra unavailable at operation time, the
    exchange boundary must raise a bounded SourceExchangeError with actionable
    '[s3]' guidance and a versioned CLI envelope — never a foreign exception
    or traceback."""
    import sys as _sys

    from lumio_wiki.env_loader import KB_PATH_ENV_VAR

    for variable in (SOURCE_EXCHANGE_ENV_VAR, KB_PATH_ENV_VAR):
        monkeypatch.delenv(variable, raising=False)
    world = _baseline_world(tmp_path)
    artifact = world["snapshot"]
    exchange = _exchange("contributor")  # resolved client created beforehand
    monkeypatch.setitem(_sys.modules, "obstore", None)  # import boundary only

    with pytest.raises(SourceExchangeError) as refused:
        upload_source_transfer(artifact, exchange=exchange)
    assert "[s3]" in str(refused.value)
    _assert_no_disclosure(str(refused.value))

    code = main(
        [
            "source-exchange",
            "upload",
            "--file",
            str(artifact),
            "--exchange",
            f"s3://{_BUCKET}/{_PREFIX}",
            "--json",
        ]
    )
    assert code == 2
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["schema_version"] == 1
    _assert_no_disclosure(json.dumps(envelope))


def test_exchange_profile_requires_explicit_kb(tmp_path, capsys, monkeypatch):
    """F6: profile-mode exchange selection must require the ACTUAL --kb even
    when an ambient LUMIO_KB_PATH default exists; nothing may be uploaded."""
    from lumio_wiki.env_loader import (
        ARTIFACT_RETENTION_ENV_VAR,
        KB_PATH_ENV_VAR,
        SOURCE_REGISTRY_ENV_VAR,
        SOURCE_STORE_ENV_VAR,
    )

    for variable in (
        SOURCE_EXCHANGE_ENV_VAR,
        SOURCE_REGISTRY_ENV_VAR,
        SOURCE_STORE_ENV_VAR,
        ARTIFACT_RETENTION_ENV_VAR,
    ):
        monkeypatch.delenv(variable, raising=False)
    world, artifact, facts = _upload_baseline(tmp_path)
    second = tmp_path / "transfer" / "second.tar"
    export_source_baseline(
        world["kb"],
        world["base"],
        source_registry=SourceRegistry(tmp_path / "maintainer" / "registry"),
        output_path=second,
    )
    profile = tmp_path / "contributor" / "profile.json"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "namespace": NAMESPACE,
                "source_registry": str((tmp_path / "contributor" / "registry").resolve()),
                "retention": "required",
                "artifact_store": {
                    "kind": "local",
                    "root": str((tmp_path / "contributor" / "store").resolve()),
                },
                "exchange": {
                    "kind": "s3",
                    "bucket": _BUCKET,
                    "prefix": _PREFIX,
                    "endpoint": _ENDPOINT,
                    "region": _os.environ.get("LUMIO_S3_REGION", "us-east-1"),
                    "url_style": "path",
                    "credentials": {
                        "access_key_id_env": "LUMIO_S3_TEST_CONTRIBUTOR_ACCESS_KEY_ID",
                        "secret_access_key_env": "LUMIO_S3_TEST_CONTRIBUTOR_SECRET_ACCESS_KEY",
                    },
                },
            }
        )
    )
    # Ambient default populated (the exact escape the review found).
    monkeypatch.setenv(KB_PATH_ENV_VAR, str(world["kb"]))

    remote_calls = {"count": 0}
    saved = {}
    for name in ("put", "copy", "head", "get", "list"):
        saved[name] = getattr(obstore, name)

        def _wrapper(*args, __name=name, **kwargs):
            remote_calls["count"] += 1
            return saved[__name](*args, **kwargs)

        setattr(obstore, name, _wrapper)
    try:
        code = main(
            [
                "source-exchange",
                "upload",
                "--file",
                str(second),
                "--private-profile",
                str(profile),
                "--json",
            ]
        )
    finally:
        for name, real in saved.items():
            setattr(obstore, name, real)
    envelope = json.loads(capsys.readouterr().out)
    assert code == 2
    assert envelope["schema_version"] == 1
    assert envelope["error"]["code"] == "invalid_private_profile"
    assert remote_calls["count"] == 0, "network mutation before the explicit --kb refusal"


def _denied_read_wrapper_for_key(key: str):
    """Wrap obstore.head/get so reads of ONE key use the real denied-role
    store (actual PermissionDeniedError), everything else delegating."""
    denied_store = _role_store("denied")
    real_head = obstore.head
    real_get = obstore.get
    fired = {"denied_reads": 0, "raw": None}

    def wrapped_head(store, path, *args, **kwargs):
        if path == key and store is not denied_store:
            fired["denied_reads"] += 1
            try:
                return real_head(denied_store, path, *args, **kwargs)
            except Exception as exc:  # record the real denial for the oracle
                fired["raw"] = type(exc).__name__
                raise
        return real_head(store, path, *args, **kwargs)

    def wrapped_get(store, path, *args, **kwargs):
        if path == key and store is not denied_store:
            fired["denied_reads"] += 1
            try:
                return real_get(denied_store, path, *args, **kwargs)
            except Exception as exc:
                fired["raw"] = type(exc).__name__
                raise
        return real_get(store, path, *args, **kwargs)

    return (real_head, real_get), (wrapped_head, wrapped_get), fired


def _lost_copy_wrapper():
    """Wrap obstore.copy: perform the real copy (AlreadyExists is the remote
    outcome for an existing immutable final), then lose the response."""
    from obstore.exceptions import AlreadyExistsError

    real_copy = obstore.copy

    def wrapped(store, from_, to, *args, **kwargs):
        try:
            real_copy(store, from_, to, *args, **kwargs)
        except AlreadyExistsError:
            pass
        raise RuntimeError("injected lost copy response")

    return real_copy, wrapped


def _lost_ready_put_wrapper():
    """Wrap obstore.put: the ready.json create-only put hits the real
    AlreadyExists outcome, then the response is lost."""
    from obstore.exceptions import AlreadyExistsError

    real_put = obstore.put

    def wrapped(store, path, *args, **kwargs):
        try:
            return real_put(store, path, *args, **kwargs)
        except AlreadyExistsError:
            raise RuntimeError("injected lost ready response") from None

    return real_put, wrapped


def _conflicting_baseline_for(tmp_path: Path, artifact: Path) -> Path:
    conflicting = tmp_path / "transfer" / "review-conflicting.tar"
    _conflicting_archive("source-baseline", _manifest_of(artifact), conflicting)
    return conflicting


@pytest.mark.parametrize("scenario", ["copy_existing_denied", "ready_existing_denied"])
def test_exchange_recovery_denied_verification_is_not_conflict(scenario, tmp_path):
    """F7a/b: on an identical retry, a DENIED verification/comparison read
    must stay exchange_access_denied — never an identity conflict."""
    world, artifact, facts = _upload_baseline(tmp_path)
    key = (
        _raw_key(facts["transfer_id"], "transfer.tar")
        if scenario == "copy_existing_denied"
        else _raw_key(facts["transfer_id"], "ready.json")
    )
    (real_head, real_get), (wrapped_head, wrapped_get), fired = _denied_read_wrapper_for_key(key)
    obstore.head = wrapped_head
    obstore.get = wrapped_get
    try:
        with pytest.raises(SourceExchangeError) as refused:
            upload_source_transfer(artifact, exchange=_exchange("contributor"))
    finally:
        obstore.head = real_head
        obstore.get = real_get
    assert fired["denied_reads"] >= 1 and fired["raw"] == "PermissionDeniedError"
    assert refused.value.code == "exchange_access_denied"


@pytest.mark.parametrize("scenario", ["copy_lost_denied", "ready_lost_denied"])
def test_exchange_recovery_lost_response_denied_is_not_invalid(scenario, tmp_path):
    """F7c/d: after a LOST copy/ready response, a denied verification read
    must stay exchange_access_denied — never a generic invalid failure."""
    world, artifact, facts = _upload_baseline(tmp_path)
    key = (
        _raw_key(facts["transfer_id"], "transfer.tar")
        if scenario == "copy_lost_denied"
        else _raw_key(facts["transfer_id"], "ready.json")
    )
    (real_head, real_get), (wrapped_head, wrapped_get), fired = _denied_read_wrapper_for_key(key)
    real_copy, wrapped_copy = _lost_copy_wrapper()
    real_put, wrapped_put = _lost_ready_put_wrapper()
    obstore.head = wrapped_head
    obstore.get = wrapped_get
    if scenario == "copy_lost_denied":
        obstore.copy = wrapped_copy
    else:
        obstore.put = wrapped_put
    try:
        with pytest.raises(SourceExchangeError) as refused:
            upload_source_transfer(artifact, exchange=_exchange("contributor"))
    finally:
        obstore.head = real_head
        obstore.get = real_get
        obstore.copy = real_copy
        obstore.put = real_put
    assert fired["denied_reads"] >= 1 and fired["raw"] == "PermissionDeniedError"
    assert refused.value.code == "exchange_access_denied"


def test_exchange_recovery_lost_copy_with_different_final_is_conflict(tmp_path):
    """F7e: a LOST copy response over an established DIFFERENT final object
    must be reported as exchange_conflict, with the immutable bytes kept."""
    world, artifact, facts = _upload_baseline(tmp_path)
    conflicting = _conflicting_baseline_for(tmp_path, artifact)
    real_copy, wrapped_copy = _lost_copy_wrapper()
    obstore.copy = wrapped_copy
    try:
        with pytest.raises(SourceExchangeError) as refused:
            upload_source_transfer(conflicting, exchange=_exchange("contributor"))
    finally:
        obstore.copy = real_copy
    assert refused.value.code == "exchange_conflict"
    maintainer_raw = _role_store("maintainer")
    remote_digest, _total = _remote_digest(
        maintainer_raw, _raw_key(facts["transfer_id"], "transfer.tar")
    )
    assert remote_digest == facts["sha256"]  # original final bytes unchanged


def test_exchange_recovery_lost_ready_with_different_record_is_conflict(tmp_path):
    """F7f: a LOST ready response against an established DIFFERENT completion
    record must be reported as exchange_conflict, with the record unchanged."""
    world, artifact, facts = _upload_baseline(tmp_path)
    conflicting = _conflicting_baseline_for(tmp_path, artifact)
    conflicting_digest = hashlib.sha256(conflicting.read_bytes()).hexdigest()
    # Remote state: final already carries the conflicting bytes; the existing
    # completion record names the ORIGINAL artifact (independently known
    # different bytes), so the converging copy path reaches the ready seam.
    raw = _role_store("contributor")
    obstore.put(raw, _raw_key(facts["transfer_id"], "transfer.tar"), conflicting.read_bytes())
    original_ready = {
        "schema_version": 1,
        "kind": "source-baseline",
        "transfer_id": facts["transfer_id"],
        "byte_count": facts["byte_count"],
        "sha256": facts["sha256"],
    }
    obstore.put(
        raw,
        _raw_key(facts["transfer_id"], "ready.json"),
        json.dumps(original_ready).encode(),
    )
    real_put, wrapped_put = _lost_ready_put_wrapper()
    obstore.put = wrapped_put
    try:
        with pytest.raises(SourceExchangeError) as refused:
            upload_source_transfer(conflicting, exchange=_exchange("contributor"))
    finally:
        obstore.put = real_put
    assert refused.value.code == "exchange_conflict"
    ready_now = json.loads(
        bytes(
            obstore.get(
                _role_store("maintainer"), _raw_key(facts["transfer_id"], "ready.json")
            ).bytes()
        )
    )
    assert ready_now == original_ready  # record unchanged
    assert conflicting_digest != facts["sha256"]  # the payloads genuinely differ
