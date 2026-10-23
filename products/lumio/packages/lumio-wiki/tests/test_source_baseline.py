"""Metadata-only Source Baseline Snapshot bootstrap (spec 0010 §5.1, plan J0/V0).

Two focused journeys over independently authored facts. The positive journey
exports a maintainer snapshot for one exact nonempty managed Git base and
bootstraps a fresh contributor: every exact base binding resolves afterwards,
prior history and one locally retained version survive reimport, no original
files appear, and required-retention publication still refuses the missing
original. The mismatch family hand-crafts invalid v1 artifacts directly from
the documented transfer contract — never from exporter output — and asserts
each refusal leaves the canonical registry untouched.

Oracles are the fixture itself: known source bytes digested with
``hashlib.sha256``, hand-written bindings, and filesystem/registry state.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from lumio_wiki.artifact_store import (
    LocalDirectoryArtifactStore,
    RetentionRequiredError,
    activation_binding_hook,
    capture_binding_entries,
    retain_artifact,
)
from lumio_wiki.cli import (
    ARTIFACT_RETENTION_ENV_VAR,
    SOURCE_REGISTRY_ENV_VAR,
    SOURCE_STORE_ENV_VAR,
    main,
)
from lumio_wiki.git_authoring import capture_revision
from lumio_wiki.source_references import (
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceManifest,
    serialize_source_reference_manifest,
    validate_source_references,
)
from lumio_wiki.source_registry import SourceRegistry

NAMESPACE = "urn:uuid:8f2f6c2e-3b1d-4e6a-9c21-7d0e5a4b1c02"
OTHER_NAMESPACE = "urn:uuid:00000000-0000-0000-0000-000000000001"

MANUAL_BYTES = b"Operate the hydraulic press only after the safety guard is locked."
MEMO_BYTES = b"Shift memo: replace the coolant filter weekly, Sundays before startup."
MEMO_LOCAL_BYTES = b"Unrelated local memo never transferred by the bootstrap."
MANUAL_DIGEST = hashlib.sha256(MANUAL_BYTES).hexdigest()
MEMO_DIGEST = hashlib.sha256(MEMO_BYTES).hexdigest()
MEMO_LOCAL_DIGEST = hashlib.sha256(MEMO_LOCAL_BYTES).hexdigest()

MANUAL_ID = "operator-manual"
MEMO_ID = "maintenance-memo"
MEMO_LOCAL_ID = "local-memo"
PRESS_ENTITY = "entity:hydraulic-press"
NOTE_ENTITY = "entity:service-memo"

ORIGIN_CREATED_AT = "2026-10-01T09:15:00+00:00"

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
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {args} failed: {result.stderr.decode()}")
    return result.stdout.decode().strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test Author")
    return path


def _write_base_kb(repo: Path) -> Path:
    kb = repo / "kb"
    kb.mkdir(parents=True)
    (kb / "lumio.yaml").write_text(CONTROL)
    pages = {
        "concepts/hydraulic-press.md": _managed_page(
            "Hydraulic Press", PRESS_ENTITY, "machine", MANUAL_ID
        ),
        "concepts/service-memo.md": _managed_page("Service Memo", NOTE_ENTITY, "note", MEMO_ID),
    }
    for rel, content in pages.items():
        (kb / rel).parent.mkdir(parents=True, exist_ok=True)
        (kb / rel).write_text(content)
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        serialize_source_reference_manifest(
            SourceReferenceManifest(
                version=1,
                namespace=NAMESPACE,
                sources={MANUAL_ID: "active", MEMO_ID: "active"},
                bindings={
                    PRESS_ENTITY: {MANUAL_ID: MANUAL_DIGEST},
                    NOTE_ENTITY: {MEMO_ID: MEMO_DIGEST},
                },
            )
        )
    )
    return kb


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _maintainer_fixture(tmp_path: Path) -> tuple[Path, Path, SourceRegistry, str]:
    """A nonempty managed base plus its maintainer registry (independent facts)."""
    repo = _init_repo(tmp_path / "maintainer" / "repo")
    kb = _write_base_kb(repo)
    base = _commit(repo, "baseline revision")
    registry = SourceRegistry(tmp_path / "maintainer" / "registry")
    registry.register_version(
        MANUAL_ID, MANUAL_BYTES, filename="manual.pdf", content_type="application/pdf"
    )
    registry.register_version(MEMO_ID, MEMO_BYTES)
    # Unrelated maintainer history never enters the snapshot.
    registry.register_version("internal-note", b"never transferred")
    return repo, kb, registry, base


def _craft_archive(
    path: Path, manifest: dict, *, extra_entry: tuple[str, bytes] | None = None
) -> str:
    """Hand-build one v1 snapshot archive from the documented container contract."""
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
        if extra_entry is not None:
            name, data = extra_entry
            tar.addfile(_info(name, len(data)), io.BytesIO(data))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buffer.getvalue())
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def _fixture_manifest(kb: Path, base: str, **overrides: object) -> dict:
    """The valid v1 manifest for the fixture base, built from fixture facts."""
    manifest: dict[str, object] = {
        "schema_version": 1,
        "kind": "source-baseline",
        "transfer_id": "b" * 64,
        "namespace": NAMESPACE,
        "kb_subtree": "kb",
        "revision": base,
        "source_manifest_digest": hashlib.sha256(
            (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).read_bytes()
        ).hexdigest(),
        "bindings": [
            {
                "entity_id": PRESS_ENTITY,
                "source_id": MANUAL_ID,
                "content_hash": MANUAL_DIGEST,
            },
            {
                "entity_id": NOTE_ENTITY,
                "source_id": MEMO_ID,
                "content_hash": MEMO_DIGEST,
            },
        ],
        "versions": [
            {
                "source_id": MANUAL_ID,
                "content_hash": MANUAL_DIGEST,
                "size": len(MANUAL_BYTES),
                "content_type": "application/pdf",
                "filename": "manual.pdf",
                "origin_created_at": ORIGIN_CREATED_AT,
            },
            {
                "source_id": MEMO_ID,
                "content_hash": MEMO_DIGEST,
                "size": len(MEMO_BYTES),
                "content_type": None,
                "filename": None,
                "origin_created_at": ORIGIN_CREATED_AT,
            },
        ],
    }
    manifest.update(overrides)
    return manifest


def _contributor_clone(tmp_path: Path, maintainer_repo: Path) -> Path:
    clone = tmp_path / "contributor" / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(maintainer_repo), str(clone)],
        capture_output=True,
        check=True,
    )
    return clone / "kb"


def _registry_state_bytes(registry_dir: Path) -> bytes | None:
    state = registry_dir / "sources.json"
    return state.read_bytes() if state.exists() else None


def _tree_files(root: Path) -> set[str]:
    if not root.exists():
        return set()
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


# ---------------------------------------------------------------------------
# V0 positive: history and retained state survive; no artifacts appear.
# ---------------------------------------------------------------------------


def test_metadata_bootstrap_preserves_history_without_artifacts(tmp_path, capsys):
    maintainer_repo, mkb, mreg, base = _maintainer_fixture(tmp_path)
    # Pre-export fixture fact: the maintainer's registration timestamp for
    # the exact manual version — the origin the snapshot must preserve.
    maintainer_manual = mreg.find_version(MANUAL_ID, MANUAL_DIGEST)
    assert maintainer_manual is not None
    expected_origin = maintainer_manual.created_at

    # Maintainer export through the public CLI.
    snapshot = tmp_path / "transfer" / "baseline.tar"
    code = main(
        [
            "source-bootstrap",
            "export",
            str(mkb),
            "--revision",
            base,
            "--output",
            str(snapshot),
            "--source-registry",
            str(mreg.root),
            "--json",
        ]
    )
    assert code == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["ok"] is True
    assert exported["kind"] == "source-baseline"
    assert exported["namespace"] == NAMESPACE
    assert exported["revision"] == base
    assert exported["kb_subtree"] == "kb"
    assert exported["binding_count"] == 2
    assert exported["version_count"] == 2
    # Independent digest oracle: the archive's own bytes.
    assert exported["snapshot_sha256"] == hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert re.fullmatch(r"[0-9a-f]{64}", exported["transfer_id"])

    # The archive is manifest-only and private: no originals ever enter it.
    with tarfile.open(snapshot, "r:") as tar:
        members = tar.getmembers()
        assert [member.name for member in members] == ["manifest.json"]
        stream = tar.extractfile(members[0])
        assert stream is not None
        payload = stream.read()
    assert MANUAL_BYTES not in payload and MEMO_BYTES not in payload
    assert b"artifact_available" not in payload

    # Repeated export of the same captured facts is byte-identical.
    second = tmp_path / "transfer" / "baseline-2.tar"
    main(
        [
            "source-bootstrap",
            "export",
            str(mkb),
            "--revision",
            base,
            "--output",
            str(second),
            "--source-registry",
            str(mreg.root),
            "--json",
        ]
    )
    capsys.readouterr()
    assert second.read_bytes() == snapshot.read_bytes()

    # Fresh contributor: separate clone, registry, and artifact store. It
    # legitimately holds memo's original (retained) plus unrelated local
    # history; the manual original is absent.
    ckb = _contributor_clone(tmp_path, maintainer_repo)
    creg_dir = tmp_path / "contributor" / "registry"
    creg = SourceRegistry(creg_dir)
    creg.register_version(MEMO_ID, MEMO_BYTES)
    cstore_dir = tmp_path / "contributor" / "artifacts"
    cstore_dir.mkdir(parents=True)
    cstore = LocalDirectoryArtifactStore(cstore_dir)
    retain_artifact(
        cstore,
        creg,
        source_id=MEMO_ID,
        raw_bytes=MEMO_BYTES,
        content_type=None,
        filename=None,
    )
    creg.register_version(MEMO_LOCAL_ID, MEMO_LOCAL_BYTES)
    retained = creg.find_version(MEMO_ID, MEMO_DIGEST)
    assert retained is not None and retained.artifact_available is True
    store_files_before = _tree_files(cstore_dir)
    state_before = _registry_state_bytes(creg_dir)

    digest = exported["snapshot_sha256"]

    # Inspect through the public CLI: read-only, explicit readiness.
    code = main(
        [
            "source-bootstrap",
            "inspect",
            str(ckb),
            "--snapshot",
            str(snapshot),
            "--digest",
            digest,
            "--revision",
            base,
            "--source-registry",
            str(creg_dir),
            "--json",
        ]
    )
    assert code == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["ok"] is True
    assert preview["ready"] is True
    assert preview["blockers"] == []
    assert preview["versions_to_add"] == 1  # manual: metadata only
    assert preview["versions_to_reuse"] == 1  # memo: already registered locally
    assert preview["binding_count"] == 2
    assert re.fullmatch(r"[0-9a-f]{64}", preview["confirmation_digest"])
    assert _registry_state_bytes(creg_dir) == state_before

    # Profile selection (spec 0010 §2.1): one explicit file, registry-only
    # resolution; the declared local artifact store is never opened.
    profile = tmp_path / "contributor" / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "namespace": NAMESPACE,
                "source_registry": str(creg_dir.resolve()),
                "retention": "required",
                "artifact_store": {
                    "kind": "local",
                    "root": str((tmp_path / "contributor" / "unused-store").resolve()),
                },
            }
        )
    )
    code = main(
        [
            "source-bootstrap",
            "import",
            str(ckb),
            "--snapshot",
            str(snapshot),
            "--digest",
            digest,
            "--revision",
            base,
            "--private-profile",
            str(profile),
            "--json",
        ]
    )
    assert code == 0
    unconfirmed = json.loads(capsys.readouterr().out)
    assert unconfirmed["status"] == "preview"
    assert unconfirmed["versions_added"] == 0
    assert unconfirmed["versions_reused"] == 0
    assert _registry_state_bytes(creg_dir) == state_before

    # Profile mode is exclusive: a competing explicit registry flag refuses.
    code = main(
        [
            "source-bootstrap",
            "import",
            str(ckb),
            "--snapshot",
            str(snapshot),
            "--digest",
            digest,
            "--revision",
            base,
            "--source-registry",
            str(creg_dir),
            "--private-profile",
            str(profile),
            "--json",
        ]
    )
    assert code == 2
    conflict = json.loads(capsys.readouterr().out)
    assert conflict["error"]["code"] == "conflicting_private_selection"
    assert _registry_state_bytes(creg_dir) == state_before

    # Confirmed import binds the exact preview; wrong confirmation refuses.
    wrong_confirm = "c" * 64
    code = main(
        [
            "source-bootstrap",
            "import",
            str(ckb),
            "--snapshot",
            str(snapshot),
            "--digest",
            digest,
            "--revision",
            base,
            "--private-profile",
            str(profile),
            "--confirm",
            wrong_confirm,
            "--json",
        ]
    )
    assert code == 2
    refused = json.loads(capsys.readouterr().out)
    assert refused["error"]["code"] == "invalid_source_baseline"
    assert _registry_state_bytes(creg_dir) == state_before

    confirmation = unconfirmed["confirmation_digest"]
    assert confirmation == preview["confirmation_digest"]
    code = main(
        [
            "source-bootstrap",
            "import",
            str(ckb),
            "--snapshot",
            str(snapshot),
            "--digest",
            digest,
            "--revision",
            base,
            "--private-profile",
            str(profile),
            "--confirm",
            confirmation,
            "--json",
        ]
    )
    assert code == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["status"] == "imported"
    assert imported["versions_added"] == 1
    assert imported["versions_reused"] == 1
    assert imported["provenance_records"] == 2
    assert imported["kind"] == "source-baseline"

    # Every exact base binding resolves; the complete-candidate authoring
    # prerequisite (spec 0010 D0) holds through the real validation seam.
    captured = capture_revision(ckb, base)
    assert validate_source_references(captured.manifest, captured.kb, registry=creg) == []

    # Metadata came from the fixture, not the exporter: exact values.
    manual = creg.find_version(MANUAL_ID, MANUAL_DIGEST)
    assert manual is not None
    assert manual.size == len(MANUAL_BYTES)
    assert manual.filename == "manual.pdf"
    assert manual.content_type == "application/pdf"
    assert manual.artifact_available is False  # metadata never asserts retention
    memo = creg.find_version(MEMO_ID, MEMO_DIGEST)
    assert memo is not None and memo.artifact_available is True  # no downgrade
    assert creg.assigned_namespace() == NAMESPACE

    # Prior unrelated history survives.
    local = creg.get(MEMO_LOCAL_ID)
    assert [version.content_hash for version in local.versions] == [MEMO_LOCAL_DIGEST]

    # No original files were created: the artifact store is unchanged and the
    # local registration time stays honest (origin provenance is separate).
    assert _tree_files(cstore_dir) == store_files_before
    origin_files = sorted((creg_dir / "baseline-imports").rglob("*.json"))
    assert len(origin_files) == 2
    manual_origin_records = sorted(
        (creg_dir / "baseline-imports" / MANUAL_ID / MANUAL_DIGEST).glob("*.json")
    )
    assert len(manual_origin_records) == 1
    origin = json.loads(manual_origin_records[0].read_text())
    assert origin["kind"] == "source-baseline-import"
    assert origin["namespace"] == NAMESPACE
    assert origin["revision"] == base
    assert origin["snapshot_digest"] == digest
    assert origin["origin_created_at"] == expected_origin
    assert manual.created_at != expected_origin

    # Reimport is idempotent: history, retained state and provenance converge.
    code = main(
        [
            "source-bootstrap",
            "import",
            str(ckb),
            "--snapshot",
            str(snapshot),
            "--digest",
            digest,
            "--revision",
            base,
            "--private-profile",
            str(profile),
            "--confirm",
            confirmation,
            "--json",
        ]
    )
    assert code == 0
    reimported = json.loads(capsys.readouterr().out)
    assert reimported["versions_added"] == 0
    assert reimported["versions_reused"] == 2
    still_retained = creg.find_version(MEMO_ID, MEMO_DIGEST)
    assert still_retained is not None and still_retained.artifact_available is True
    assert creg.get(MEMO_LOCAL_ID).versions[-1].content_hash == MEMO_LOCAL_DIGEST
    assert len(sorted((creg_dir / "baseline-imports").rglob("*.json"))) == 2
    assert validate_source_references(captured.manifest, captured.kb, registry=creg) == []

    # Required-retention publication still refuses the missing original: the
    # real activation gate re-verifies live against the artifact store.
    hook = activation_binding_hook(artifact_store=cstore, registry=creg, required=True)
    entries = capture_binding_entries(creg, captured.kb.pages)
    prepared = SimpleNamespace(
        version="v1",
        fingerprint="fixed-test-fingerprint",
        pages=captured.kb.pages,
        binding_entries=entries,
    )
    with pytest.raises(RetentionRequiredError, match=MANUAL_ID):
        hook(prepared)


# ---------------------------------------------------------------------------
# V0 negative: contract-derived mismatches refuse without canonical mutation.
# ---------------------------------------------------------------------------


def _assert_refused(
    capsys, ckb, snapshot, digest, base, creg_dir, *, confirm: str | None = None
) -> None:
    argv = [
        "source-bootstrap",
        "import",
        str(ckb),
        "--snapshot",
        str(snapshot),
        "--digest",
        digest,
        "--revision",
        base,
        "--source-registry",
        str(creg_dir),
        "--json",
    ]
    if confirm is not None:
        argv += ["--confirm", confirm]
    before = _registry_state_bytes(creg_dir)
    code = main(argv)
    captured = capsys.readouterr()
    assert code == 2, captured
    error = json.loads(captured.out)
    assert error["ok"] is False
    assert error["error"]["code"] == "invalid_source_baseline"
    assert _registry_state_bytes(creg_dir) == before


@pytest.mark.parametrize(
    "case",
    [
        "wrong_namespace",
        "wrong_base_revision",
        "missing_coverage",
        "immutable_conflict",
        "registry_namespace_conflict",
        "forged_availability",
        "forged_payload_entry",
        "wrong_kind",
        "version_record_limit",
        "manifest_bytes_limit",
        "archive_size_limit",
        "digest_mismatch",
    ],
)
def test_metadata_bootstrap_rejects_mismatch(case, tmp_path, capsys):
    maintainer_repo, mkb, _mreg, base = _maintainer_fixture(tmp_path)
    ckb = _contributor_clone(tmp_path, maintainer_repo)
    creg_dir = tmp_path / "contributor" / "registry"
    crafted = tmp_path / "transfer" / "crafted.tar"

    if case == "wrong_namespace":
        digest = _craft_archive(crafted, _fixture_manifest(mkb, base, namespace=OTHER_NAMESPACE))
        _assert_refused(capsys, ckb, crafted, digest, base, creg_dir)
        return

    if case == "wrong_base_revision":
        page = maintainer_repo / "kb" / "concepts" / "service-memo.md"
        page.write_text(page.read_text() + "\nEdited after the base.\n")
        other_base = _commit(maintainer_repo, "successor revision")
        assert other_base != base
        subprocess.run(
            ["git", "-C", str(tmp_path / "contributor" / "clone"), "fetch", "-q", "origin"],
            capture_output=True,
            check=True,
        )
        digest = _craft_archive(crafted, _fixture_manifest(mkb, other_base))
        _assert_refused(capsys, ckb, crafted, digest, base, creg_dir)
        return

    if case == "missing_coverage":
        partial = _fixture_manifest(mkb, base)
        partial["bindings"] = partial["bindings"][:1]  # drop the memo binding
        digest = _craft_archive(crafted, partial)
        _assert_refused(capsys, ckb, crafted, digest, base, creg_dir)
        return

    if case == "immutable_conflict":
        # The contributor already holds the same exact bytes recorded under a
        # different populated immutable filename: an explicit conflict.
        creg = SourceRegistry(creg_dir)
        creg.register_version(MANUAL_ID, MANUAL_BYTES, filename="other-name.pdf")
        digest = _craft_archive(crafted, _fixture_manifest(mkb, base))
        code = main(
            [
                "source-bootstrap",
                "inspect",
                str(ckb),
                "--snapshot",
                str(crafted),
                "--digest",
                digest,
                "--revision",
                base,
                "--source-registry",
                str(creg_dir),
                "--json",
            ]
        )
        assert code == 0
        preview = json.loads(capsys.readouterr().out)
        assert preview["ready"] is False
        assert any("immutable metadata conflict" in blocker for blocker in preview["blockers"])
        _assert_refused(
            capsys, ckb, crafted, digest, base, creg_dir, confirm=preview["confirmation_digest"]
        )
        conflicting = creg.find_version(MANUAL_ID, MANUAL_DIGEST)
        assert conflicting is not None and conflicting.filename == "other-name.pdf"
        return

    if case == "registry_namespace_conflict":
        # A registry already explicitly assigned to another namespace is
        # never silently re-scoped.
        creg = SourceRegistry(creg_dir)
        creg.register_version_metadata(
            "unrelated",
            MANUAL_DIGEST,
            size=1,
            namespace=OTHER_NAMESPACE,
        )
        digest = _craft_archive(crafted, _fixture_manifest(mkb, base))
        code = main(
            [
                "source-bootstrap",
                "inspect",
                str(ckb),
                "--snapshot",
                str(crafted),
                "--digest",
                digest,
                "--revision",
                base,
                "--source-registry",
                str(creg_dir),
                "--json",
            ]
        )
        assert code == 0
        preview = json.loads(capsys.readouterr().out)
        assert preview["ready"] is False
        assert any("namespace" in blocker for blocker in preview["blockers"])
        _assert_refused(
            capsys, ckb, crafted, digest, base, creg_dir, confirm=preview["confirmation_digest"]
        )
        assert creg.assigned_namespace() == OTHER_NAMESPACE
        return

    if case == "forged_availability":
        forged = _fixture_manifest(mkb, base)
        forged["versions"][0]["artifact_available"] = True
        digest = _craft_archive(crafted, forged)
        _assert_refused(capsys, ckb, crafted, digest, base, creg_dir)
        return

    if case == "forged_payload_entry":
        digest = _craft_archive(
            crafted,
            _fixture_manifest(mkb, base),
            extra_entry=(f"artifacts/{MANUAL_DIGEST}", b"forged original bytes"),
        )
        _assert_refused(capsys, ckb, crafted, digest, base, creg_dir)
        return

    if case == "wrong_kind":
        digest = _craft_archive(crafted, _fixture_manifest(mkb, base, kind="source-handoff"))
        _assert_refused(capsys, ckb, crafted, digest, base, creg_dir)
        return

    if case == "version_record_limit":
        oversized = _fixture_manifest(mkb, base)
        bindings = []
        versions = []
        for index in range(10_001):
            content_hash = hashlib.sha256(f"pad-{index}".encode()).hexdigest()
            bindings.append(
                {
                    "entity_id": f"entity:pad-{index}",
                    "source_id": f"pad{index:05d}",
                    "content_hash": content_hash,
                }
            )
            versions.append(
                {
                    "source_id": f"pad{index:05d}",
                    "content_hash": content_hash,
                    "size": 1,
                    "content_type": None,
                    "filename": None,
                    "origin_created_at": ORIGIN_CREATED_AT,
                }
            )
        oversized["bindings"] = bindings
        oversized["versions"] = versions
        digest = _craft_archive(crafted, oversized)
        _assert_refused(capsys, ckb, crafted, digest, base, creg_dir)
        return

    if case == "manifest_bytes_limit":
        # Complete, valid binding coverage with ONE oversized field: the
        # serialized manifest measures above the 4 MiB ceiling but below the
        # container cap, so the manifest-limit refusal is what must fire.
        oversized = _fixture_manifest(mkb, base)
        bindings = list(oversized["bindings"])
        bindings[0] = {
            "entity_id": PRESS_ENTITY + "-" + "a" * (4 * 1024 * 1024 + 262_144),
            "source_id": MANUAL_ID,
            "content_hash": MANUAL_DIGEST,
        }
        oversized["bindings"] = bindings
        payload = json.dumps(oversized, sort_keys=True, separators=(",", ":")).encode()
        assert 4 * 1024 * 1024 < len(payload) < 4 * 1024 * 1024 + 512 * 1024
        digest = _craft_archive(crafted, oversized)
        before = _registry_state_bytes(creg_dir)
        code = main(
            [
                "source-bootstrap",
                "import",
                str(ckb),
                "--snapshot",
                str(crafted),
                "--digest",
                digest,
                "--revision",
                base,
                "--source-registry",
                str(creg_dir),
            ]
        )
        refusal = capsys.readouterr()
        assert code == 2, refusal
        assert "4 MiB" in refusal.err  # specifically the manifest ceiling
        assert _registry_state_bytes(creg_dir) == before
        return

    if case == "archive_size_limit":
        oversized = _fixture_manifest(mkb, base)
        oversized["bindings"] = [
            {
                "entity_id": "entity:" + "a" * (6 * 1024 * 1024),
                "source_id": MANUAL_ID,
                "content_hash": MANUAL_DIGEST,
            }
        ]
        digest = _craft_archive(crafted, oversized)
        _assert_refused(capsys, ckb, crafted, digest, base, creg_dir)
        return

    assert case == "digest_mismatch"
    digest = _craft_archive(crafted, _fixture_manifest(mkb, base))
    _assert_refused(capsys, ckb, crafted, "d" * 64, base, creg_dir)


# ---------------------------------------------------------------------------
# Review regressions (j0-review.md): contract guards pinning the accepted
# F1–F5 product repairs.
# ---------------------------------------------------------------------------


def _oversized_sparse_archive(path: Path, size: int) -> str:
    """A sparse oversized archive plus its independently streamed digest."""
    with open(path, "wb") as handle:
        handle.truncate(size)
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_baseline_archive_limit_precedes_payload_read(tmp_path, capsys, monkeypatch):
    """F1: refusal of an oversized archive must not read it in one giant chunk."""
    maintainer_repo, mkb, _mreg, base = _maintainer_fixture(tmp_path)
    ckb = _contributor_clone(tmp_path, maintainer_repo)
    creg_dir = tmp_path / "contributor" / "registry"
    oversized = tmp_path / "transfer" / "oversized.tar"
    oversized.parent.mkdir(parents=True, exist_ok=True)
    expected = _oversized_sparse_archive(oversized, 6 * 1024 * 1024)

    whole_file_reads: list[int] = []
    original_read_bytes = Path.read_bytes

    def _bounded_read_bytes(self):
        data = original_read_bytes(self)
        if self == oversized:
            whole_file_reads.append(len(data))
        return data

    monkeypatch.setattr(Path, "read_bytes", _bounded_read_bytes)
    code = main(
        [
            "source-bootstrap",
            "import",
            str(ckb),
            "--snapshot",
            str(oversized),
            "--digest",
            expected,
            "--revision",
            base,
            "--source-registry",
            str(creg_dir),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2, captured
    assert json.loads(captured.out)["ok"] is False
    # The observable read bound: the oversized archive is never loaded in one
    # whole-file read; refusal must not depend on allocating its bytes.
    assert not whole_file_reads or max(whole_file_reads) <= 1024 * 1024, whole_file_reads
    assert not (creg_dir / "sources.json").exists()


@pytest.mark.parametrize("mutation", ["bindings_null", "versions_integer", "schema_float"])
def test_baseline_malformed_types_are_structured(mutation, tmp_path, capsys):
    """F2: malformed collection types and non-integer schema versions refuse."""
    maintainer_repo, mkb, _mreg, base = _maintainer_fixture(tmp_path)
    ckb = _contributor_clone(tmp_path, maintainer_repo)
    creg_dir = tmp_path / "contributor" / "registry"
    manifest = _fixture_manifest(mkb, base)
    if mutation == "bindings_null":
        manifest["bindings"] = None
    elif mutation == "versions_integer":
        manifest["versions"] = 7
    else:
        manifest["schema_version"] = 1.0
    digest = _craft_archive(tmp_path / "transfer" / "crafted.tar", manifest)
    code = main(
        [
            "source-bootstrap",
            "import",
            str(ckb),
            "--snapshot",
            str(tmp_path / "transfer" / "crafted.tar"),
            "--digest",
            digest,
            "--revision",
            base,
            "--source-registry",
            str(creg_dir),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2, captured
    error = json.loads(captured.out)
    assert error["ok"] is False
    assert error["error"]["code"] == "invalid_source_baseline"
    assert not (creg_dir / "sources.json").exists()


def test_baseline_import_rechecks_batch_before_mutation(tmp_path, capsys, monkeypatch):
    """F3: a validation conflict mid-import must not leave a partial baseline."""
    maintainer_repo, mkb, _mreg, base = _maintainer_fixture(tmp_path)
    ckb = _contributor_clone(tmp_path, maintainer_repo)
    creg_dir = tmp_path / "contributor" / "registry"
    creg = SourceRegistry(creg_dir)
    creg.register_version(MEMO_LOCAL_ID, MEMO_LOCAL_BYTES)  # unrelated history
    crafted = tmp_path / "transfer" / "crafted.tar"
    digest = _craft_archive(crafted, _fixture_manifest(mkb, base))

    code = main(
        [
            "source-bootstrap",
            "import",
            str(ckb),
            "--snapshot",
            str(crafted),
            "--digest",
            digest,
            "--revision",
            base,
            "--source-registry",
            str(creg_dir),
            "--json",
        ]
    )
    assert code == 0
    confirmation = json.loads(capsys.readouterr().out)["confirmation_digest"]

    # A normal second writer registers the later-sorted source (same exact
    # digest, conflicting populated filename) right after its last optimistic
    # lookup and before the canonical import mutation.
    original_find = SourceRegistry.find_version
    fired: list[bool] = []

    def _interleaved_find(self, source_id, content_hash):
        found = original_find(self, source_id, content_hash)
        if source_id == MANUAL_ID and not fired:
            fired.append(True)
            SourceRegistry(self.root).register_version(
                MANUAL_ID, MANUAL_BYTES, filename="conflicting.pdf"
            )
        return found

    monkeypatch.setattr(SourceRegistry, "find_version", _interleaved_find)
    code = main(
        [
            "source-bootstrap",
            "import",
            str(ckb),
            "--snapshot",
            str(crafted),
            "--digest",
            digest,
            "--revision",
            base,
            "--source-registry",
            str(creg_dir),
            "--confirm",
            confirmation,
            "--json",
        ]
    )
    out = capsys.readouterr().out
    assert code == 2, out
    assert json.loads(out)["ok"] is False
    assert fired  # the cooperating writer actually ran inside the window

    registry = SourceRegistry(creg_dir)
    ids = {source.source_id for source in registry.list()}
    assert ids == {MEMO_LOCAL_ID, MANUAL_ID}  # no earlier-sorted baseline source added
    conflicting = registry.find_version(MANUAL_ID, MANUAL_DIGEST)
    assert conflicting is not None and conflicting.filename == "conflicting.pdf"
    assert registry.find_version(MEMO_ID, MEMO_DIGEST) is None
    assert not (creg_dir / "baseline-imports").exists()  # no purported origin records
    local = registry.get(MEMO_LOCAL_ID)
    assert [version.content_hash for version in local.versions] == [MEMO_LOCAL_DIGEST]


def test_baseline_export_refuses_other_registry_namespace(tmp_path, capsys):
    """F4: export refuses a registry explicitly assigned to another namespace."""
    maintainer_repo, mkb, _mreg, base = _maintainer_fixture(tmp_path)
    del maintainer_repo
    other_dir = tmp_path / "other" / "registry"
    other = SourceRegistry(other_dir)
    # Same exact IDs/digests the base binds — the namespace scope is the only
    # difference, so missing versions can never be the refusal reason.
    other.register_version(
        MANUAL_ID, MANUAL_BYTES, filename="manual.pdf", content_type="application/pdf"
    )
    other.register_version(MEMO_ID, MEMO_BYTES)
    other.register_version_metadata("seed", MANUAL_DIGEST, size=1, namespace=OTHER_NAMESPACE)
    before = _registry_state_bytes(other_dir)

    snapshot = tmp_path / "transfer" / "must-not-exist.tar"
    code = main(
        [
            "source-bootstrap",
            "export",
            str(mkb),
            "--revision",
            base,
            "--output",
            str(snapshot),
            "--source-registry",
            str(other_dir),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2, captured
    assert json.loads(captured.out)["ok"] is False
    assert not snapshot.exists()
    assert _registry_state_bytes(other_dir) == before


@pytest.mark.parametrize("case", ["digest_mismatch", "missing_registry"])
def test_baseline_error_envelope_is_versioned(case, tmp_path, capsys, monkeypatch):
    """F5: new bootstrap JSON failures carry schema_version 1."""
    for variable in (SOURCE_REGISTRY_ENV_VAR, SOURCE_STORE_ENV_VAR, ARTIFACT_RETENTION_ENV_VAR):
        monkeypatch.delenv(variable, raising=False)
    maintainer_repo, mkb, _mreg, base = _maintainer_fixture(tmp_path)
    ckb = _contributor_clone(tmp_path, maintainer_repo)
    creg_dir = tmp_path / "contributor" / "registry"
    crafted = tmp_path / "transfer" / "crafted.tar"
    digest = _craft_archive(crafted, _fixture_manifest(mkb, base))
    if case == "digest_mismatch":
        argv = [
            "source-bootstrap",
            "import",
            str(ckb),
            "--snapshot",
            str(crafted),
            "--digest",
            "e" * 64,
            "--revision",
            base,
            "--source-registry",
            str(creg_dir),
            "--json",
        ]
    else:  # missing_registry: no registry selection at all
        argv = [
            "source-bootstrap",
            "import",
            str(ckb),
            "--snapshot",
            str(crafted),
            "--digest",
            digest,
            "--revision",
            base,
            "--json",
        ]
    code = main(argv)
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload.get("schema_version") == 1
    assert payload["ok"] is False
    assert payload["error"]["code"]
    assert payload["error"]["message"]
