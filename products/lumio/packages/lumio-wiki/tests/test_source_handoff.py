"""Full Source Handoff Bundle transfer (spec 0010 §5, plan 0010 J3/V3).

Two focused journeys over independently authored facts. The positive journey
exports one real contribution range in a contributor checkout (intentional
existing-source update, a new source, and a second new source sharing the
first one's digest), imports it into a separate maintainer checkout with its
own registry/store through the CLI profile and explicit paths, retries an
interrupted import, adds a supplementary exact reference, and checks reuse
after a same-bindings rebase — always against handwritten bytes digested
with ``hashlib.sha256`` and real Git state. The mismatch family hand-crafts
invalid v1 bundles directly from the documented transfer contract — never
from exporter output — and asserts each named refusal leaves the canonical
registry, store and provenance untouched.
"""

from __future__ import annotations

import builtins
import hashlib
import io
import json
import os
import re
import subprocess
import tarfile
from pathlib import Path

import pytest
from lumio_wiki.artifact_store import LocalDirectoryArtifactStore, retain_artifact
from lumio_wiki.cli import (
    ARTIFACT_RETENTION_ENV_VAR,
    SOURCE_REGISTRY_ENV_VAR,
    SOURCE_STORE_ENV_VAR,
    main,
)
from lumio_wiki.git_authoring import capture_revision
from lumio_wiki.source_handoff import (
    SourceHandoffError,
    import_source_handoff,
)
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
MEMO2_BYTES = b"Shift memo v2: replace the coolant filter weekly and log the pressure."
GLOSS_BYTES = b"Shop glossary: the guard interlock stops the press within one second."
GLOSS2_BYTES = b"Glossary competitor bytes under the same source identity."
MEMO2_SUFFIX = b" Added after review."
MEMO2_BYTES = MEMO_BYTES + MEMO2_SUFFIX

MANUAL_DIGEST = hashlib.sha256(MANUAL_BYTES).hexdigest()
MEMO_DIGEST = hashlib.sha256(MEMO_BYTES).hexdigest()
MEMO2_DIGEST = hashlib.sha256(MEMO2_BYTES).hexdigest()
GLOSS_DIGEST = hashlib.sha256(GLOSS_BYTES).hexdigest()
GLOSS2_DIGEST = hashlib.sha256(GLOSS2_BYTES).hexdigest()

MANUAL_ID = "operator-manual"
MEMO_ID = "maintenance-memo"
GLOSS_ID = "shop-glossary"
ALIAS_ID = "field-glossary"
ARCHIVE_POLICY_ID = "archive-policy"
ARCHIVE_POLICY_BYTES = b"Unrelated maintainer retention policy never transferred."
ARCHIVE_POLICY_DIGEST = hashlib.sha256(ARCHIVE_POLICY_BYTES).hexdigest()

PRESS_ENTITY = "entity:hydraulic-press"
NOTE_ENTITY = "entity:service-memo"
GLOSS_ENTITY = "entity:shop-glossary"
FIELD_ENTITY = "entity:field-glossary"

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


def _git_bytes(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
    )
    return result.stdout


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
    # The BASE manifest is the hand-authored pre-change fact: only the two
    # original sources are active and the memo still binds its v1 digest.
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


def _write_manifest(kb: Path) -> None:
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        serialize_source_reference_manifest(
            SourceReferenceManifest(
                version=1,
                namespace=NAMESPACE,
                sources={
                    MANUAL_ID: "active",
                    MEMO_ID: "active",
                    GLOSS_ID: "active",
                    ALIAS_ID: "active",
                },
                bindings={
                    PRESS_ENTITY: {MANUAL_ID: MANUAL_DIGEST},
                    NOTE_ENTITY: {MEMO_ID: MEMO2_DIGEST},
                    GLOSS_ENTITY: {GLOSS_ID: GLOSS_DIGEST},
                    FIELD_ENTITY: {ALIAS_ID: GLOSS_DIGEST},
                },
            )
        )
    )


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _contributor_world(tmp_path: Path):
    """A contributor checkout with a committed base, contribution and rebase,
    its own registry/store holding every selected original, plus unrelated
    private history that must never be transferred."""
    repo = _init_repo(tmp_path / "contributor" / "repo")
    kb = _write_base_kb(repo)
    base = _commit(repo, "baseline revision")
    # The contribution: one new source, a second new source sharing its exact
    # bytes (one payload, two distinct identities), and an intentional update
    # of the existing memo source, all reflected in the reviewed manifest.
    (kb / "concepts" / "shop-glossary.md").write_text(
        _managed_page("Shop Glossary", GLOSS_ENTITY, "note", GLOSS_ID)
    )
    (kb / "concepts" / "field-glossary.md").write_text(
        _managed_page("Field Glossary", FIELD_ENTITY, "note", ALIAS_ID)
    )
    memo = kb / "concepts" / "service-memo.md"
    memo.write_text(memo.read_text() + "\nUpdated to the v2 shift memo.\n")
    _write_manifest(kb)
    contribution = _commit(repo, "contribution revision")
    # A later body-only rebase commit with unchanged source bindings.
    glossary = kb / "concepts" / "shop-glossary.md"
    glossary.write_text(glossary.read_text() + "\nRebased body edit only.\n")
    rebase = _commit(repo, "rebase revision with unchanged bindings")

    # Fixture guard (hand-authored facts, not exporter output): the base
    # manifest binds the memo's v1 digest and knows no glossary source; the
    # contribution manifest adds both glossary identities and the v2 digest.
    base_manifest = _git_bytes(repo, "show", f"{base}:kb/{SOURCE_REFERENCE_MANIFEST_BASENAME}")
    contribution_manifest = _git_bytes(
        repo, "show", f"{contribution}:kb/{SOURCE_REFERENCE_MANIFEST_BASENAME}"
    )
    assert MEMO_DIGEST.encode() in base_manifest
    assert MEMO2_DIGEST.encode() not in base_manifest
    assert GLOSS_ID.encode() not in base_manifest
    assert GLOSS_ID.encode() in contribution_manifest
    assert MEMO2_DIGEST.encode() in contribution_manifest

    registry = SourceRegistry(tmp_path / "contributor" / "registry")
    registry.register_version(
        MANUAL_ID, MANUAL_BYTES, filename="manual.pdf", content_type="application/pdf"
    )
    registry.register_version(MEMO_ID, MEMO_BYTES)
    registry.register_version(
        MEMO_ID, MEMO2_BYTES, filename="service-memo-v2.md", content_type="text/markdown"
    )
    registry.register_version(
        GLOSS_ID, GLOSS_BYTES, filename="glossary.md", content_type="text/markdown"
    )
    registry.register_version(
        ALIAS_ID, GLOSS_BYTES, filename="glossary.md", content_type="text/markdown"
    )
    registry.register_version("internal-note", b"never transferred contributor note")
    store_dir = tmp_path / "contributor" / "store"
    store_dir.mkdir(parents=True)
    store = LocalDirectoryArtifactStore(store_dir)
    for source_id, raw, filename, content_type in (
        (MANUAL_ID, MANUAL_BYTES, "manual.pdf", "application/pdf"),
        (MEMO_ID, MEMO_BYTES, None, None),
        (MEMO_ID, MEMO2_BYTES, "service-memo-v2.md", "text/markdown"),
        (GLOSS_ID, GLOSS_BYTES, "glossary.md", "text/markdown"),
        (ALIAS_ID, GLOSS_BYTES, "glossary.md", "text/markdown"),
    ):
        retain_artifact(
            store,
            registry,
            source_id=source_id,
            raw_bytes=raw,
            content_type=content_type,
            filename=filename,
        )
    return {
        "repo": repo,
        "kb": kb,
        "base": base,
        "contribution": contribution,
        "rebase": rebase,
        "registry": registry,
        "store": store,
        "store_dir": store_dir,
    }


def _maintainer_clone(tmp_path: Path, contributor_repo: Path):
    clone = tmp_path / "maintainer" / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(contributor_repo), str(clone)],
        capture_output=True,
        check=True,
    )
    return clone, clone / "kb"


def _maintainer_world(tmp_path: Path):
    """A separate maintainer checkout with an empty private registry holding
    only unrelated history and an empty artifact store."""
    clone, mkb = _maintainer_clone(tmp_path, tmp_path / "contributor" / "repo")
    mreg_dir = tmp_path / "maintainer" / "registry"
    mreg = SourceRegistry(mreg_dir)
    mreg.register_version(ARCHIVE_POLICY_ID, ARCHIVE_POLICY_BYTES)
    mstore_dir = tmp_path / "maintainer" / "store"
    mstore_dir.mkdir(parents=True)
    return clone, mkb, mreg, mreg_dir, LocalDirectoryArtifactStore(mstore_dir), mstore_dir


def _tree_files(root: Path) -> set[str]:
    if not root.exists():
        return set()
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _registry_state_bytes(registry_dir: Path) -> bytes | None:
    state = registry_dir / "sources.json"
    return state.read_bytes() if state.exists() else None


def _provenance_files(registry_dir: Path) -> list[str]:
    root = registry_dir / "handoff-imports"
    if not root.exists():
        return []
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*.json"))


def _canonical_snapshot(mreg_dir: Path, mstore_dir: Path):
    return (
        _registry_state_bytes(mreg_dir),
        _tree_files(mstore_dir),
        _provenance_files(mreg_dir),
    )


def _craft_handoff_archive(
    path: Path,
    manifest: dict | None,
    entries: list[tuple[str, bytes]] | None = None,
    symlink_entry: str | None = None,
    manifest_bytes: bytes | None = None,
) -> str:
    """Hand-build one v1 bundle archive from the documented container contract.

    ``manifest_bytes`` (review F2) bypasses the dict serializer so a fixture
    can hand-author raw JSON carrying duplicate keys — a documented contract
    fact dict dumps cannot express.
    """
    payload = manifest_bytes
    if payload is None:
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
        if symlink_entry is not None:
            info = tarfile.TarInfo(symlink_entry)
            info.type = tarfile.SYMTYPE
            info.linkname = "elsewhere"
            info.size = 0
            info.mtime = 0
            tar.addfile(info)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buffer.getvalue())
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def _handoff_manifest_facts(repo: Path, base: str, revision: str, **overrides: object) -> dict:
    """The valid v1 handoff manifest for the fixture range, from fixture facts."""
    manifest_bytes = _git_bytes(repo, "show", f"{revision}:kb/{SOURCE_REFERENCE_MANIFEST_BASENAME}")
    manifest: dict[str, object] = {
        "schema_version": 1,
        "kind": "source-handoff",
        "transfer_id": "a" * 64,
        "namespace": NAMESPACE,
        "kb_subtree": "kb",
        "base_revision": base,
        "revision": revision,
        "source_manifest_digest": hashlib.sha256(manifest_bytes).hexdigest(),
        "bindings": [
            {
                "entity_id": FIELD_ENTITY,
                "source_id": ALIAS_ID,
                "old_digest": None,
                "new_digest": GLOSS_DIGEST,
            },
            {
                "entity_id": GLOSS_ENTITY,
                "source_id": GLOSS_ID,
                "old_digest": None,
                "new_digest": GLOSS_DIGEST,
            },
            {
                "entity_id": NOTE_ENTITY,
                "source_id": MEMO_ID,
                "old_digest": MEMO_DIGEST,
                "new_digest": MEMO2_DIGEST,
            },
        ],
        "versions": [
            {
                "source_id": ALIAS_ID,
                "content_hash": GLOSS_DIGEST,
                "size": len(GLOSS_BYTES),
                "content_type": "text/markdown",
                "filename": "glossary.md",
                "origin_created_at": ORIGIN_CREATED_AT,
                "intent": "new",
            },
            {
                "source_id": GLOSS_ID,
                "content_hash": GLOSS_DIGEST,
                "size": len(GLOSS_BYTES),
                "content_type": "text/markdown",
                "filename": "glossary.md",
                "origin_created_at": ORIGIN_CREATED_AT,
                "intent": "new",
            },
            {
                "source_id": MEMO_ID,
                "content_hash": MEMO2_DIGEST,
                "size": len(MEMO2_BYTES),
                "content_type": "text/markdown",
                "filename": "service-memo-v2.md",
                "origin_created_at": ORIGIN_CREATED_AT,
                "intent": "update",
            },
        ],
    }
    manifest.update(overrides)
    return manifest


def _valid_entries() -> list[tuple[str, bytes]]:
    return [
        (f"artifacts/{GLOSS_DIGEST}", GLOSS_BYTES),
        (f"artifacts/{MEMO2_DIGEST}", MEMO2_BYTES),
    ]


# ---------------------------------------------------------------------------
# V3 positive: history, retry, supplementary references and rebase reuse.
# ---------------------------------------------------------------------------


def test_manual_handoff_preserves_history_and_retries(tmp_path, capsys, monkeypatch):
    world = _contributor_world(tmp_path)
    ckb, base, contribution, rebase = (
        world["kb"],
        world["base"],
        world["contribution"],
        world["rebase"],
    )
    creg, cstore_dir = world["registry"], world["store_dir"]
    # Pre-export fixture fact: the contributor's honest registration times are
    # the origin timestamps the bundle must preserve as private provenance.
    contributor_origins = {
        (source_id, digest): creg.find_version(source_id, digest).created_at
        for source_id, digest in (
            (ALIAS_ID, GLOSS_DIGEST),
            (GLOSS_ID, GLOSS_DIGEST),
            (MEMO_ID, MEMO2_DIGEST),
            (MANUAL_ID, MANUAL_DIGEST),
        )
    }
    for variable in (SOURCE_REGISTRY_ENV_VAR, SOURCE_STORE_ENV_VAR, ARTIFACT_RETENTION_ENV_VAR):
        monkeypatch.delenv(variable, raising=False)

    # Export through the private profile (spec 0010 §2.1): registry+artifacts
    # resolve together; no competing explicit flags are present.
    profile = tmp_path / "contributor" / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "namespace": NAMESPACE,
                "source_registry": str(creg.root.resolve()),
                "retention": "required",
                "artifact_store": {"kind": "local", "root": str(cstore_dir.resolve())},
            }
        )
    )
    bundle = tmp_path / "transfer" / "handoff.tar"
    code = main(
        [
            "source-handoff",
            "export",
            str(ckb),
            "--base",
            base,
            "--revision",
            contribution,
            "--output",
            str(bundle),
            "--private-profile",
            str(profile),
            "--json",
        ]
    )
    assert code == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["ok"] is True
    assert exported["kind"] == "source-handoff"
    assert exported["namespace"] == NAMESPACE
    assert exported["base_revision"] == base
    assert exported["revision"] == contribution
    assert exported["binding_count"] == 3
    assert exported["version_count"] == 3
    assert exported["payload_count"] == 2
    assert re.fullmatch(r"[0-9a-f]{64}", exported["transfer_id"])
    # Independent digest oracle: the archive's own bytes.
    assert exported["bundle_sha256"] == hashlib.sha256(bundle.read_bytes()).hexdigest()

    # Container contract: normalized headers, fixed member order, one shared
    # payload for the two distinct glossary identities, no private state.
    with tarfile.open(bundle, "r:") as tar:
        members = tar.getmembers()
        assert [member.name for member in members] == [
            "manifest.json",
            f"artifacts/{sorted([GLOSS_DIGEST, MEMO2_DIGEST])[0]}",
            f"artifacts/{sorted([GLOSS_DIGEST, MEMO2_DIGEST])[1]}",
        ]
        for member in members:
            assert member.isreg()
            assert member.mtime == 0
            assert member.uid == 0 and member.gid == 0
            assert member.uname == "" and member.gname == ""
            assert member.mode == 0o644
        manifest_stream = tar.extractfile(members[0])
        assert manifest_stream is not None
        manifest_payload = manifest_stream.read()
    assert str(tmp_path).encode() not in manifest_payload
    assert b"artifact_available" not in manifest_payload
    assert b"sources.json" not in manifest_payload
    manifest = json.loads(manifest_payload)
    assert {version["intent"] for version in manifest["versions"]} == {"new", "update"}
    intents = {(v["source_id"], v["content_hash"]): v["intent"] for v in manifest["versions"]}
    assert intents[(ALIAS_ID, GLOSS_DIGEST)] == "new"
    assert intents[(GLOSS_ID, GLOSS_DIGEST)] == "new"
    assert intents[(MEMO_ID, MEMO2_DIGEST)] == "update"
    deleted = [b for b in manifest["bindings"] if b["new_digest"] is None]
    assert deleted == []  # this range removes no binding

    # Determinism for the same captured facts INCLUDING the transfer id: a
    # second artifact's manifest differs at most by its random opaque id.
    second = tmp_path / "transfer" / "handoff-2.tar"
    main(
        [
            "source-handoff",
            "export",
            str(ckb),
            "--base",
            base,
            "--revision",
            contribution,
            "--output",
            str(second),
            "--private-profile",
            str(profile),
            "--json",
        ]
    )
    capsys.readouterr()
    with tarfile.open(second, "r:") as tar:
        second_members = tar.getmembers()
        second_stream = tar.extractfile(second_members[0])
        assert second_stream is not None
        second_manifest = json.loads(second_stream.read())
    first_without_id = dict(manifest, transfer_id=None)
    second_without_id = dict(second_manifest, transfer_id=None)
    assert first_without_id == second_without_id

    # Separate maintainer environment: its own clone, registry (holding only
    # unrelated history) and empty artifact store, selected explicitly.
    _clone, mkb, mreg, mreg_dir, mstore, mstore_dir = _maintainer_world(tmp_path)
    monkeypatch.setenv(SOURCE_STORE_ENV_VAR, str(mstore_dir))
    digest = exported["bundle_sha256"]
    state_before = _canonical_snapshot(mreg_dir, mstore_dir)

    code = main(
        [
            "source-handoff",
            "inspect",
            str(mkb),
            "--bundle",
            str(bundle),
            "--digest",
            digest,
            "--revision",
            contribution,
            "--source-registry",
            str(mreg_dir),
            "--json",
        ]
    )
    assert code == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["ok"] is True
    assert preview["ready"] is True
    assert preview["blockers"] == []
    assert preview["versions_to_add"] == 3
    assert preview["versions_to_reuse"] == 0
    assert preview["artifacts_to_retain"] == 3
    assert preview["base_revision"] == base
    assert re.fullmatch(r"[0-9a-f]{64}", preview["confirmation_digest"])
    assert _canonical_snapshot(mreg_dir, mstore_dir) == state_before

    # Import without confirmation previews; a wrong confirmation refuses with
    # a versioned error envelope and changes nothing.
    code = main(
        [
            "source-handoff",
            "import",
            str(mkb),
            "--bundle",
            str(bundle),
            "--digest",
            digest,
            "--revision",
            contribution,
            "--source-registry",
            str(mreg_dir),
            "--json",
        ]
    )
    assert code == 0
    unconfirmed = json.loads(capsys.readouterr().out)
    assert unconfirmed["status"] == "preview"
    assert unconfirmed["versions_added"] == 0
    assert _canonical_snapshot(mreg_dir, mstore_dir) == state_before

    code = main(
        [
            "source-handoff",
            "import",
            str(mkb),
            "--bundle",
            str(bundle),
            "--digest",
            digest,
            "--revision",
            contribution,
            "--source-registry",
            str(mreg_dir),
            "--confirm",
            "c" * 64,
            "--json",
        ]
    )
    assert code == 2
    refused = json.loads(capsys.readouterr().out)
    assert refused["ok"] is False
    assert refused["schema_version"] == 1
    assert refused["error"]["code"] == "invalid_source_handoff"
    assert _canonical_snapshot(mreg_dir, mstore_dir) == state_before

    confirmation = preview["confirmation_digest"]

    # One injected store failure after partial success: the metadata batch
    # committed, one artifact was retained, and the import reports incomplete.
    original_put = LocalDirectoryArtifactStore.put_artifact
    put_calls: list[str] = []

    def _failing_put(self, **kwargs):
        put_calls.append(kwargs["source_id"])
        if len(put_calls) == 2:
            raise OSError("injected partial store failure")
        return original_put(self, **kwargs)

    LocalDirectoryArtifactStore.put_artifact = _failing_put
    try:
        with pytest.raises(SourceHandoffError, match="stopped before completing"):
            import_source_handoff(
                str(mkb),
                bundle,
                contribution,
                expected_digest=digest,
                source_registry=mreg,
                artifact_store=mstore,
                confirmation=confirmation,
            )
    finally:
        LocalDirectoryArtifactStore.put_artifact = original_put
    assert put_calls == [ALIAS_ID, MEMO_ID]  # sorted source ids: one landed
    # (field-glossary < maintenance-memo < shop-glossary: the injected failure
    # hits the second put, maintenance-memo, leaving exactly one artifact)
    for source_id, digest_ in (
        (ALIAS_ID, GLOSS_DIGEST),
        (GLOSS_ID, GLOSS_DIGEST),
        (MEMO_ID, MEMO2_DIGEST),
    ):
        version = mreg.find_version(source_id, digest_)
        assert version is not None
        assert version.artifact_available is False  # never claimed unverified
    assert _tree_files(mstore_dir) == {
        f"artifacts/{ALIAS_ID}/{GLOSS_DIGEST}",
        f"artifacts/{ALIAS_ID}/{GLOSS_DIGEST}.meta",
    }
    assert _provenance_files(mreg_dir) == []
    unrelated = mreg.get(ARCHIVE_POLICY_ID)
    assert [version.content_hash for version in unrelated.versions] == [ARCHIVE_POLICY_DIGEST]

    # The convergent retry imports through the CLI with the same confirmation.
    code = main(
        [
            "source-handoff",
            "import",
            str(mkb),
            "--bundle",
            str(bundle),
            "--digest",
            digest,
            "--revision",
            contribution,
            "--source-registry",
            str(mreg_dir),
            "--confirm",
            confirmation,
            "--json",
        ]
    )
    assert code == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["status"] == "imported"
    assert imported["versions_added"] == 0  # converged metadata residue
    assert imported["versions_reused"] == 3
    assert imported["artifacts_retained"] == 3
    assert imported["provenance_records"] == 3

    # Byte-exact originals, distinct identities for the shared digest, exact
    # metadata from the fixture, honest local times, no publication state.
    assert mstore.get_artifact(source_id=MEMO_ID, content_hash=MEMO2_DIGEST) == MEMO2_BYTES
    assert mstore.get_artifact(source_id=GLOSS_ID, content_hash=GLOSS_DIGEST) == GLOSS_BYTES
    assert mstore.get_artifact(source_id=ALIAS_ID, content_hash=GLOSS_DIGEST) == GLOSS_BYTES
    assert (mstore_dir / "artifacts" / GLOSS_ID / GLOSS_DIGEST).is_file()
    assert (mstore_dir / "artifacts" / ALIAS_ID / GLOSS_DIGEST).is_file()
    for rel in _tree_files(mstore_dir):
        assert rel.startswith("artifacts/")
    memo2 = mreg.find_version(MEMO_ID, MEMO2_DIGEST)
    assert memo2 is not None
    assert memo2.size == len(MEMO2_BYTES)
    assert memo2.filename == "service-memo-v2.md"
    assert memo2.content_type == "text/markdown"
    assert memo2.artifact_available is True
    assert memo2.created_at != contributor_origins[(MEMO_ID, MEMO2_DIGEST)]
    assert mreg.assigned_namespace() == NAMESPACE
    unrelated = mreg.get(ARCHIVE_POLICY_ID)
    assert [version.content_hash for version in unrelated.versions] == [ARCHIVE_POLICY_DIGEST]
    provenance_files = _provenance_files(mreg_dir)
    assert len(provenance_files) == 3
    memo2_records = sorted((mreg_dir / "handoff-imports" / MEMO_ID / MEMO2_DIGEST).glob("*.json"))
    assert len(memo2_records) == 1
    origin = json.loads(memo2_records[0].read_text())
    assert origin["kind"] == "source-handoff-import"
    assert origin["namespace"] == NAMESPACE
    assert origin["bundle_digest"] == digest
    assert origin["base_revision"] == base
    assert origin["revision"] == contribution
    assert origin["origin_created_at"] == contributor_origins[(MEMO_ID, MEMO2_DIGEST)]
    # The complete contribution validates once every referenced version is
    # imported (the base manual original arrives with the supplementary
    # handoff below, mirroring spec 0010 §7).

    # Idempotent repeat: history, retained state and provenance converge.
    code = main(
        [
            "source-handoff",
            "import",
            str(mkb),
            "--bundle",
            str(bundle),
            "--digest",
            digest,
            "--revision",
            contribution,
            "--source-registry",
            str(mreg_dir),
            "--confirm",
            confirmation,
            "--json",
        ]
    )
    assert code == 0
    reimported = json.loads(capsys.readouterr().out)
    assert reimported["versions_added"] == 0
    assert reimported["versions_reused"] == 3
    assert len(_provenance_files(mreg_dir)) == 3
    still_available = mreg.find_version(MEMO_ID, MEMO2_DIGEST)
    assert still_available is not None and still_available.artifact_available is True

    # Supplementary exact references: the maintainer lacks the base manual
    # original still referenced by the contribution; the contributor exports
    # it as an exact reuse-intent addition through the references file.
    monkeypatch.delenv(SOURCE_STORE_ENV_VAR, raising=False)
    references = tmp_path / "transfer" / "references.json"
    references.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "references": [
                    {"source_id": MANUAL_ID, "content_hash": MANUAL_DIGEST},
                ],
            }
        )
    )
    supplementary = tmp_path / "transfer" / "supplementary.tar"
    code = main(
        [
            "source-handoff",
            "export",
            str(ckb),
            "--base",
            base,
            "--revision",
            contribution,
            "--output",
            str(supplementary),
            "--references",
            str(references),
            "--private-profile",
            str(profile),
            "--json",
        ]
    )
    assert code == 0
    exported2 = json.loads(capsys.readouterr().out)
    assert exported2["version_count"] == 4
    assert exported2["payload_count"] == 3
    monkeypatch.setenv(SOURCE_STORE_ENV_VAR, str(mstore_dir))
    code = main(
        [
            "source-handoff",
            "inspect",
            str(mkb),
            "--bundle",
            str(supplementary),
            "--digest",
            exported2["bundle_sha256"],
            "--revision",
            contribution,
            "--source-registry",
            str(mreg_dir),
            "--json",
        ]
    )
    assert code == 0
    preview2 = json.loads(capsys.readouterr().out)
    assert preview2["ready"] is True
    assert preview2["versions_to_add"] == 1
    assert preview2["versions_to_reuse"] == 3
    assert preview2["artifacts_to_retain"] == 1
    code = main(
        [
            "source-handoff",
            "import",
            str(mkb),
            "--bundle",
            str(supplementary),
            "--digest",
            exported2["bundle_sha256"],
            "--revision",
            contribution,
            "--source-registry",
            str(mreg_dir),
            "--confirm",
            preview2["confirmation_digest"],
            "--json",
        ]
    )
    assert code == 0
    imported2 = json.loads(capsys.readouterr().out)
    assert imported2["versions_added"] == 1
    manual = mreg.find_version(MANUAL_ID, MANUAL_DIGEST)
    assert manual is not None
    assert manual.filename == "manual.pdf"
    assert manual.artifact_available is True
    assert mstore.get_artifact(source_id=MANUAL_ID, content_hash=MANUAL_DIGEST) == MANUAL_BYTES
    captured = capture_revision(mkb, contribution)
    assert validate_source_references(captured.manifest, captured.kb, registry=mreg) == []

    # A rebase with unchanged bindings reuses the imported originals without
    # rewriting the original handoff revision binding.
    rebased = capture_revision(mkb, rebase)
    assert validate_source_references(rebased.manifest, rebased.kb, registry=mreg) == []
    records = sorted((mreg_dir / "handoff-imports").rglob("*.json"))
    assert all(json.loads(record.read_text())["revision"] == contribution for record in records)


# ---------------------------------------------------------------------------
# V3 negative: contract-derived mismatches refuse without canonical mutation.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case",
    [
        "wrong_namespace",
        "wrong_revision",
        "wrong_bindings",
        "corrupt_payload",
        "missing_entry",
        "duplicate_entry",
        "path_escape",
        "symlink_entry",
        "metadata_conflict",
        "ambiguous_new_source_identity",
        "cooperating_writer",
        "unknown_format",
        "wrong_kind",
        "payload_limit",
        "count_limit",
        "container_limit",
    ],
)
def test_handoff_rejects_invalid_bundle(case, tmp_path, capsys, monkeypatch):
    world = _contributor_world(tmp_path)
    base, contribution, rebase = world["base"], world["contribution"], world["rebase"]
    _clone, mkb, mreg, mreg_dir, mstore, mstore_dir = _maintainer_world(tmp_path)
    for variable in (SOURCE_REGISTRY_ENV_VAR, ARTIFACT_RETENTION_ENV_VAR):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv(SOURCE_STORE_ENV_VAR, str(mstore_dir))
    crafted = tmp_path / "transfer" / "crafted.tar"
    facts = _handoff_manifest_facts(world["repo"], base, contribution)
    message = ""

    if case == "wrong_namespace":
        namespace_manifest = facts | {"namespace": OTHER_NAMESPACE}
        digest = _craft_handoff_archive(crafted, namespace_manifest, _valid_entries())
        code = main(
            [
                "source-handoff",
                "import",
                str(mkb),
                "--bundle",
                str(crafted),
                "--digest",
                digest,
                "--revision",
                contribution,
                "--source-registry",
                str(mreg_dir),
                "--json",
            ]
        )
        assert code == 2
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["ok"] is False
        assert envelope["schema_version"] == 1
        assert envelope["error"]["code"] == "invalid_source_handoff"
        message = "cannot cross namespaces"

    elif case == "wrong_revision":
        # Self-consistent for the rebase commit; imported against the
        # contribution commit: the revision binding must refuse.
        facts = _handoff_manifest_facts(world["repo"], base, rebase)
        digest = _craft_handoff_archive(crafted, facts, _valid_entries())
        message = "bound to revision"

    elif case == "wrong_bindings":
        forged = [dict(record) for record in facts["bindings"]]
        forged[2]["old_digest"] = None  # the memo update forged as an addition
        digest = _craft_handoff_archive(crafted, facts | {"bindings": forged}, _valid_entries())
        message = "binding changes disagree"

    elif case == "corrupt_payload":
        # Same length as the real payload: only the digest check can catch it.
        flipped = bytearray(MEMO2_BYTES)
        flipped[0] ^= 0xFF
        entries = [
            (f"artifacts/{GLOSS_DIGEST}", GLOSS_BYTES),
            (f"artifacts/{MEMO2_DIGEST}", bytes(flipped)),
        ]
        digest = _craft_handoff_archive(crafted, facts, entries)
        message = "does not hash to its declared digest"

    elif case == "missing_entry":
        entries = [(f"artifacts/{GLOSS_DIGEST}", GLOSS_BYTES)]
        digest = _craft_handoff_archive(crafted, facts, entries)
        message = "no such artifact entry"

    elif case == "duplicate_entry":
        entries = [
            (f"artifacts/{GLOSS_DIGEST}", GLOSS_BYTES),
            (f"artifacts/{GLOSS_DIGEST}", GLOSS_BYTES),
            (f"artifacts/{MEMO2_DIGEST}", MEMO2_BYTES),
        ]
        digest = _craft_handoff_archive(crafted, facts, entries)
        message = "duplicate archive entry"

    elif case == "path_escape":
        entries = [*_valid_entries(), ("artifacts/../../evil.txt", b"escape")]
        digest = _craft_handoff_archive(crafted, facts, entries)
        message = "unexpected archive entry"

    elif case == "symlink_entry":
        digest = _craft_handoff_archive(
            crafted,
            facts,
            [(f"artifacts/{MEMO2_DIGEST}", MEMO2_BYTES)],
            symlink_entry=f"artifacts/{GLOSS_DIGEST}",
        )
        message = "not a regular file"

    elif case == "metadata_conflict":
        mreg.register_version(MEMO_ID, MEMO2_BYTES, filename="other-name.md")
        digest = _craft_handoff_archive(crafted, facts, _valid_entries())
        code = main(
            [
                "source-handoff",
                "inspect",
                str(mkb),
                "--bundle",
                str(crafted),
                "--digest",
                digest,
                "--revision",
                contribution,
                "--source-registry",
                str(mreg_dir),
                "--json",
            ]
        )
        assert code == 0
        preview = json.loads(capsys.readouterr().out)
        assert preview["ready"] is False
        assert any("immutable metadata conflict" in blocker for blocker in preview["blockers"])
        confirmation = preview["confirmation_digest"]
        snapshot = _canonical_snapshot(mreg_dir, mstore_dir)
        code = main(
            [
                "source-handoff",
                "import",
                str(mkb),
                "--bundle",
                str(crafted),
                "--digest",
                digest,
                "--revision",
                contribution,
                "--source-registry",
                str(mreg_dir),
                "--confirm",
                confirmation,
            ]
        )
        captured = capsys.readouterr()
        assert code == 2
        assert "blocked" in captured.err
        assert _canonical_snapshot(mreg_dir, mstore_dir) == snapshot
        conflicting = mreg.find_version(MEMO_ID, MEMO2_DIGEST)
        assert conflicting is not None and conflicting.filename == "other-name.md"
        return

    elif case == "ambiguous_new_source_identity":
        mreg.register_version(GLOSS_ID, GLOSS2_BYTES)
        digest = _craft_handoff_archive(crafted, facts, _valid_entries())
        code = main(
            [
                "source-handoff",
                "inspect",
                str(mkb),
                "--bundle",
                str(crafted),
                "--digest",
                digest,
                "--revision",
                contribution,
                "--source-registry",
                str(mreg_dir),
                "--json",
            ]
        )
        assert code == 0
        preview = json.loads(capsys.readouterr().out)
        assert preview["ready"] is False
        assert any("ambiguous new source identity" in blocker for blocker in preview["blockers"])
        confirmation = preview["confirmation_digest"]
        snapshot = _canonical_snapshot(mreg_dir, mstore_dir)
        code = main(
            [
                "source-handoff",
                "import",
                str(mkb),
                "--bundle",
                str(crafted),
                "--digest",
                digest,
                "--revision",
                contribution,
                "--source-registry",
                str(mreg_dir),
                "--confirm",
                confirmation,
            ]
        )
        captured = capsys.readouterr()
        assert code == 2
        assert "blocked" in captured.err
        assert _canonical_snapshot(mreg_dir, mstore_dir) == snapshot
        return

    elif case == "cooperating_writer":
        digest = _craft_handoff_archive(crafted, facts, _valid_entries())
        code = main(
            [
                "source-handoff",
                "inspect",
                str(mkb),
                "--bundle",
                str(crafted),
                "--digest",
                digest,
                "--revision",
                contribution,
                "--source-registry",
                str(mreg_dir),
                "--json",
            ]
        )
        assert code == 0
        confirmation = json.loads(capsys.readouterr().out)["confirmation_digest"]
        # A cooperating writer registers the new-intent source identity right
        # after the import's last optimistic read and before the locked
        # metadata commit (j0-review F3 pattern): the batch must refuse under
        # its fresh locked state instead of silently appending the version.
        original_list = SourceRegistry.list
        fired: list[bool] = []

        def _interleaved_list(self):
            state = original_list(self)
            if self.root == mreg.root and not fired:
                fired.append(True)
                SourceRegistry(self.root).register_version(GLOSS_ID, GLOSS2_BYTES)
            return state

        monkeypatch.setattr(SourceRegistry, "list", _interleaved_list)
        snapshot = _canonical_snapshot(mreg_dir, mstore_dir)
        code = main(
            [
                "source-handoff",
                "import",
                str(mkb),
                "--bundle",
                str(crafted),
                "--digest",
                digest,
                "--revision",
                contribution,
                "--source-registry",
                str(mreg_dir),
                "--confirm",
                confirmation,
            ]
        )
        captured = capsys.readouterr()
        assert code == 2, captured
        assert fired  # the cooperating writer really ran inside the window
        assert "already knows that source" in captured.err
        after = _canonical_snapshot(mreg_dir, mstore_dir)
        assert after[1] == snapshot[1]  # store untouched
        assert after[2] == snapshot[2]  # no purported provenance
        registry = SourceRegistry(mreg_dir)
        gloss = registry.get(GLOSS_ID)
        assert [version.content_hash for version in gloss.versions] == [GLOSS2_DIGEST]
        assert registry.find_version(ALIAS_ID, GLOSS_DIGEST) is None
        assert registry.find_version(MEMO_ID, MEMO2_DIGEST) is None
        return

    elif case == "unknown_format":
        digest = _craft_handoff_archive(crafted, facts | {"schema_version": 2}, _valid_entries())
        message = "unsupported handoff manifest schema_version"

    elif case == "wrong_kind":
        kind_manifest = facts | {"kind": "source-baseline"}
        digest = _craft_handoff_archive(crafted, kind_manifest, _valid_entries())
        message = "full-source importer"

    elif case == "payload_limit":
        import lumio_wiki.source_handoff as source_handoff

        monkeypatch.setattr(source_handoff, "ORIGINAL_MAX_BYTES", 8)
        digest = _craft_handoff_archive(crafted, facts, _valid_entries())
        message = "per-original size ceiling"

    elif case == "count_limit":
        import lumio_wiki.source_handoff as source_handoff

        monkeypatch.setattr(source_handoff, "MAX_UNIQUE_PAYLOADS", 1)
        digest = _craft_handoff_archive(crafted, facts, _valid_entries())
        message = "unique-payload ceiling"

    else:  # container_limit: a real transfer file that grows after the stat
        import lumio_wiki.source_handoff as source_handoff

        monkeypatch.setattr(source_handoff, "TOTAL_PAYLOAD_MAX_BYTES", 64 * 1024)
        monkeypatch.setattr(source_handoff, "CONTAINER_OVERHEAD_MAX_BYTES", 64 * 1024)
        ceiling = source_handoff.MANIFEST_MAX_BYTES + 128 * 1024
        digest = _craft_handoff_archive(crafted, facts, _valid_entries())
        assert crafted.stat().st_size < ceiling
        grown_size = ceiling + 1024 * 1024
        grown_digest = hashlib.sha256(crafted.read_bytes())
        grown_digest.update(b"\x00" * (grown_size - crafted.stat().st_size))
        reads: list[int] = []
        grown_once: list[bool] = []

        class _RecordingReader:
            def __init__(self, handle):
                self._handle = handle

            def read(self, size=-1, /):
                data = self._handle.read(size)
                reads.append(len(data))
                return data

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return self._handle.__exit__(*exc_info)

            def close(self):
                self._handle.close()

        real_open = builtins.open

        def _growing_open(file, mode="r", *args, **kwargs):
            if str(file) == str(crafted) and "r" in mode and "b" in mode and not grown_once:
                grown_once.append(True)
                os.truncate(crafted, grown_size)
                return _RecordingReader(real_open(file, mode, *args, **kwargs))
            return real_open(file, mode, *args, **kwargs)

        # Exact canonical preservation (review F5): snapshot BEFORE the call,
        # compare exactly after the refusal — the registry carries unrelated
        # history here, so an absence oracle would be wrong.
        snapshot = _canonical_snapshot(mreg_dir, mstore_dir)
        monkeypatch.setattr(source_handoff, "open", _growing_open, raising=False)
        code = main(
            [
                "source-handoff",
                "import",
                str(mkb),
                "--bundle",
                str(crafted),
                "--digest",
                grown_digest.hexdigest(),
                "--revision",
                contribution,
                "--source-registry",
                str(mreg_dir),
            ]
        )
        captured = capsys.readouterr()
        assert code == 2, captured
        assert grown_once  # the wrapper really armed the grown transfer file
        assert reads  # the importer really consumed bytes through it
        assert sum(reads) <= ceiling + 1, reads
        assert "container bound" in captured.err
        assert _canonical_snapshot(mreg_dir, mstore_dir) == snapshot
        return

    # Default refusal path: the named message on stderr, a nonzero exit, and
    # the canonical registry/store/provenance exactly as they were.
    snapshot = _canonical_snapshot(mreg_dir, mstore_dir)
    code = main(
        [
            "source-handoff",
            "import",
            str(mkb),
            "--bundle",
            str(crafted),
            "--digest",
            digest,
            "--revision",
            contribution,
            "--source-registry",
            str(mreg_dir),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2, captured
    assert message in captured.err
    assert _canonical_snapshot(mreg_dir, mstore_dir) == snapshot


# ---------------------------------------------------------------------------
# Review F1-F4 regressions: containment, structured errors, tar extension
# records, and the independent container-overhead ceiling.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case",
    [
        "sdk_registry_root",
        "sdk_local_store_root",
        "sdk_bundle_symlink",
        "cli_fallback_registry",
        "cli_references_file",
    ],
)
def test_handoff_private_paths_stay_outside_repository(case, tmp_path, capsys, monkeypatch):
    """F1: private selections and transfer paths stay outside the entire
    Content Repository — resolved symlinks included (spec 0010 §1/§2.1)."""
    world = _contributor_world(tmp_path)
    base, contribution = world["base"], world["contribution"]
    _clone, mkb, mreg, mreg_dir, mstore, mstore_dir = _maintainer_world(tmp_path)
    for variable in (SOURCE_REGISTRY_ENV_VAR, ARTIFACT_RETENTION_ENV_VAR):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv(SOURCE_STORE_ENV_VAR, str(mstore_dir))

    # A native-valid handcrafted transfer plus a real confirmation obtained
    # with CLEAN selections; only the path selection is violated afterwards.
    crafted = tmp_path / "transfer" / "crafted.tar"
    digest = _craft_handoff_archive(
        crafted, _handoff_manifest_facts(world["repo"], base, contribution), _valid_entries()
    )
    code = main(
        [
            "source-handoff",
            "inspect",
            str(mkb),
            "--bundle",
            str(crafted),
            "--digest",
            digest,
            "--revision",
            contribution,
            "--source-registry",
            str(mreg_dir),
            "--json",
        ]
    )
    assert code == 0
    confirmation = json.loads(capsys.readouterr().out)["confirmation_digest"]
    snapshot = _canonical_snapshot(mreg_dir, mstore_dir)
    private_root = _clone / "private"
    private_root.mkdir()

    if case == "sdk_registry_root":
        private_registry_dir = private_root / "registry"
        private_registry_dir.mkdir()
        with pytest.raises(SourceHandoffError, match="content repository"):
            import_source_handoff(
                str(mkb),
                crafted,
                contribution,
                expected_digest=digest,
                source_registry=SourceRegistry(private_registry_dir),
                artifact_store=mstore,
                confirmation=confirmation,
            )
        assert not (private_registry_dir / "sources.json").exists()
        assert not (private_registry_dir / "handoff-imports").exists()
        assert _canonical_snapshot(mreg_dir, mstore_dir) == snapshot
        return

    if case == "sdk_local_store_root":
        private_store_dir = private_root / "originals"
        private_store_dir.mkdir()
        with pytest.raises(SourceHandoffError, match="content repository"):
            import_source_handoff(
                str(mkb),
                crafted,
                contribution,
                expected_digest=digest,
                source_registry=mreg,
                artifact_store=LocalDirectoryArtifactStore(private_store_dir),
                confirmation=confirmation,
            )
        assert not any(private_store_dir.rglob("*"))
        assert _canonical_snapshot(mreg_dir, mstore_dir) == snapshot
        return

    if case == "sdk_bundle_symlink":
        # The bundle path itself lives outside the repository but RESOLVES
        # into it: a plain string check on the link path would miss it.
        inside = private_root / "bundle.tar"
        inside.write_bytes(crafted.read_bytes())
        link = tmp_path / "transfer" / "link.tar"
        link.symlink_to(inside)
        with pytest.raises(SourceHandoffError, match="content repository"):
            import_source_handoff(
                str(mkb),
                link,
                contribution,
                expected_digest=digest,
                source_registry=mreg,
                artifact_store=mstore,
                confirmation=confirmation,
            )
        assert _canonical_snapshot(mreg_dir, mstore_dir) == snapshot
        return

    if case == "cli_fallback_registry":
        private_registry_dir = private_root / "registry"
        private_registry_dir.mkdir()
        code = main(
            [
                "source-handoff",
                "import",
                str(mkb),
                "--bundle",
                str(crafted),
                "--digest",
                digest,
                "--revision",
                contribution,
                "--source-registry",
                str(private_registry_dir),
                "--confirm",
                confirmation,
            ]
        )
        captured = capsys.readouterr()
        assert code == 2, captured
        assert "content repository" in captured.err
        assert not (private_registry_dir / "sources.json").exists()
        assert not (private_registry_dir / "handoff-imports").exists()
        assert _canonical_snapshot(mreg_dir, mstore_dir) == snapshot
        return

    # cli_references_file: the export-side reference selection lives inside
    # the contributor Content Repository; refusal precedes the private read
    # and no bundle is written.
    monkeypatch.setenv(SOURCE_STORE_ENV_VAR, str(world["store_dir"]))
    references = world["repo"] / "private-references.json"
    references.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "references": [{"source_id": MANUAL_ID, "content_hash": MANUAL_DIGEST}],
            }
        )
    )
    output = tmp_path / "transfer" / "refs-bundle.tar"
    code = main(
        [
            "source-handoff",
            "export",
            str(world["kb"]),
            "--base",
            base,
            "--revision",
            contribution,
            "--output",
            str(output),
            "--references",
            str(references),
            "--source-registry",
            str(world["registry"].root),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2, captured
    assert "content repository" in captured.err
    assert not output.exists()


@pytest.mark.parametrize(
    "case",
    [
        "manifest_unknown_field",
        "manifest_duplicate_key",
        "references_duplicate_key",
        "references_missing_file",
        "export_output_non_directory_parent",
    ],
)
def test_handoff_errors_are_structured(case, tmp_path, capsys, monkeypatch):
    """F2: malformed manifests/references selections and ordinary transfer I/O
    failures surface as the versioned bounded error envelope — never an
    escaping exception (spec 0010 §8; baseline semantics unchanged)."""
    world = _contributor_world(tmp_path)
    base, contribution = world["base"], world["contribution"]
    _clone, mkb, mreg, mreg_dir, _mstore, mstore_dir = _maintainer_world(tmp_path)
    for variable in (SOURCE_REGISTRY_ENV_VAR, ARTIFACT_RETENTION_ENV_VAR):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv(SOURCE_STORE_ENV_VAR, str(mstore_dir))
    crafted = tmp_path / "transfer" / "crafted.tar"
    facts = _handoff_manifest_facts(world["repo"], base, contribution)
    import_argv_tail = [
        "--bundle",
        str(crafted),
        "--digest",
        "",
        "--revision",
        contribution,
        "--source-registry",
        str(mreg_dir),
        "--json",
    ]

    if case == "manifest_unknown_field":
        mutated = facts | {"unexpected": True}
        digest = _craft_handoff_archive(crafted, mutated, _valid_entries())
        # SDK boundary first: the handoff parser owns its contract error type.
        with pytest.raises(SourceHandoffError):
            import_source_handoff(
                str(mkb),
                crafted,
                contribution,
                expected_digest=digest,
                source_registry=mreg,
                artifact_store=LocalDirectoryArtifactStore(mstore_dir),
            )
        argv = ["source-handoff", "import", str(mkb), *import_argv_tail]
        argv[argv.index("--digest") + 1] = digest
    elif case == "manifest_duplicate_key":
        raw = json.dumps(facts, sort_keys=True, separators=(",", ":"))
        raw = raw[:-1] + ',"namespace":"' + NAMESPACE + '"}'
        digest = _craft_handoff_archive(
            crafted, None, _valid_entries(), manifest_bytes=raw.encode("utf-8")
        )
        argv = ["source-handoff", "import", str(mkb), *import_argv_tail]
        argv[argv.index("--digest") + 1] = digest
    elif case == "references_duplicate_key":
        monkeypatch.setenv(SOURCE_STORE_ENV_VAR, str(world["store_dir"]))
        (tmp_path / "transfer").mkdir(parents=True, exist_ok=True)
        references = tmp_path / "transfer" / "references.json"
        references.write_text('{"schema_version":1,"schema_version":1,"references":[]}')
        argv = [
            "source-handoff",
            "export",
            str(world["kb"]),
            "--base",
            base,
            "--revision",
            contribution,
            "--output",
            str(tmp_path / "transfer" / "out.tar"),
            "--references",
            str(references),
            "--source-registry",
            str(world["registry"].root),
            "--json",
        ]
    elif case == "references_missing_file":
        monkeypatch.setenv(SOURCE_STORE_ENV_VAR, str(world["store_dir"]))
        argv = [
            "source-handoff",
            "export",
            str(world["kb"]),
            "--base",
            base,
            "--revision",
            contribution,
            "--output",
            str(tmp_path / "transfer" / "out.tar"),
            "--references",
            str(tmp_path / "transfer" / "missing.json"),
            "--source-registry",
            str(world["registry"].root),
            "--json",
        ]
    else:  # export_output_non_directory_parent: a regular file as parent.
        monkeypatch.setenv(SOURCE_STORE_ENV_VAR, str(world["store_dir"]))
        (tmp_path / "transfer").mkdir(parents=True, exist_ok=True)
        blocker = tmp_path / "transfer" / "plain-file"
        blocker.write_text("a regular file, not a directory")
        argv = [
            "source-handoff",
            "export",
            str(world["kb"]),
            "--base",
            base,
            "--revision",
            contribution,
            "--output",
            str(blocker / "handoff.tar"),
            "--source-registry",
            str(world["registry"].root),
            "--json",
        ]

    code = main(argv)
    captured = capsys.readouterr()
    assert code == 2, captured
    envelope = json.loads(captured.out)
    assert envelope["ok"] is False
    assert envelope["schema_version"] == 1
    assert envelope["error"]["code"] == "invalid_source_handoff"
    assert envelope["error"]["message"] == "the source handoff operation failed"


@pytest.mark.parametrize("variant", ["gnu_longname", "pax_extended"])
def test_handoff_rejects_tar_extensions_before_body(variant, tmp_path, capsys, monkeypatch):
    """F3: only regular physical records are grammar-legal; GNU/PAX extension
    headers are refused as unsupported records before their bodies are
    consumed (plan 0010 transfer formats v1)."""
    import lumio_wiki.source_handoff as source_handoff

    world = _contributor_world(tmp_path)
    base, contribution = world["base"], world["contribution"]
    _clone, mkb, _mreg, mreg_dir, _mstore, mstore_dir = _maintainer_world(tmp_path)
    for variable in (SOURCE_REGISTRY_ENV_VAR, ARTIFACT_RETENTION_ENV_VAR):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv(SOURCE_STORE_ENV_VAR, str(mstore_dir))
    facts = _handoff_manifest_facts(world["repo"], base, contribution)
    manifest_payload = json.dumps(facts, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _raw_info(name: str, size: int, type_flag: bytes) -> tarfile.TarInfo:
        info = tarfile.TarInfo(name)
        info.size = size
        info.mode = 0o644
        info.uid = 0
        info.gid = 0
        info.uname = ""
        info.gname = ""
        info.mtime = 0
        info.type = type_flag
        return info

    crafted = tmp_path / "transfer" / f"crafted-{variant}.tar"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        if variant == "gnu_longname":
            # Documented tar fact: a GNU long-name record is a physical
            # '././@LongLink' member with typeflag 'L' whose body REPLACES the
            # following header's name — so the yielded member looks like a
            # perfectly valid manifest.json while a forbidden physical record
            # preceded it.
            body = b"manifest.json\x00"
            tar.addfile(
                _raw_info("././@LongLink", len(body), tarfile.GNUTYPE_LONGNAME),
                io.BytesIO(body),
            )
        else:
            # Documented tar fact: a PAX extended header is a physical 'x'
            # record whose "<len> path=<value>\n" body overrides the following
            # header's name the same way.
            line = b"22 path=manifest.json\n"
            assert len(line) == 22
            tar.addfile(_raw_info("PaxHeader", len(line), tarfile.XHDTYPE), io.BytesIO(line))
        tar.addfile(
            _raw_info("mn", len(manifest_payload), tarfile.REGTYPE),
            io.BytesIO(manifest_payload),
        )
        for name, data in _valid_entries():
            tar.addfile(_raw_info(name, len(data), tarfile.REGTYPE), io.BytesIO(data))
    crafted.parent.mkdir(parents=True, exist_ok=True)
    crafted.write_bytes(buffer.getvalue())
    digest = hashlib.sha256(buffer.getvalue()).hexdigest()

    # Independent physical-header facts: the FIRST 512-byte block carries the
    # extension record's typeflag at offset 156, and the fixture stays tiny.
    raw = crafted.read_bytes()
    expected_flag = b"L" if variant == "gnu_longname" else b"x"
    assert raw[156:157] == expected_flag, raw[148:157]
    assert crafted.stat().st_size < 64 * 1024

    reads: list[int] = []
    real_open = builtins.open

    class _RecordingReader:
        def __init__(self, handle):
            self._handle = handle

        def read(self, size=-1, /):
            data = self._handle.read(size)
            reads.append(len(data))
            return data

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return self._handle.__exit__(*exc_info)

        def close(self):
            self._handle.close()

    def _recording_open(file, mode="r", *args, **kwargs):
        if str(file) == str(crafted) and "r" in mode and "b" in mode:
            return _RecordingReader(real_open(file, mode, *args, **kwargs))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(source_handoff, "open", _recording_open, raising=False)
    snapshot = _canonical_snapshot(mreg_dir, mstore_dir)
    code = main(
        [
            "source-handoff",
            "import",
            str(mkb),
            "--bundle",
            str(crafted),
            "--digest",
            digest,
            "--revision",
            contribution,
            "--source-registry",
            str(mreg_dir),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2, captured
    assert "unsupported tar extension record" in captured.err
    assert reads  # the importer really consumed bytes through the wrapper
    assert max(reads) <= 1024 * 1024, reads  # no size-proportional single read
    assert sum(reads) <= crafted.stat().st_size, reads  # single pass, nothing re-read
    # Literal before-extension-body boundary (supplemental disposition): the
    # refusal may consume at most the FIRST physical 512-byte tar header.
    assert sum(reads) <= 512, reads
    assert _canonical_snapshot(mreg_dir, mstore_dir) == snapshot


def test_handoff_rejects_excess_overhead(tmp_path, capsys, monkeypatch):
    """F4: container overhead is bounded independently of the unused payload
    allowance (plan 0010 transfer bounds)."""
    import lumio_wiki.source_handoff as source_handoff

    world = _contributor_world(tmp_path)
    base, contribution = world["base"], world["contribution"]
    _clone, mkb, _mreg, mreg_dir, _mstore, mstore_dir = _maintainer_world(tmp_path)
    for variable in (SOURCE_REGISTRY_ENV_VAR, ARTIFACT_RETENTION_ENV_VAR):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv(SOURCE_STORE_ENV_VAR, str(mstore_dir))
    facts = _handoff_manifest_facts(world["repo"], base, contribution)
    crafted = tmp_path / "transfer" / "tiny.tar"
    _craft_handoff_archive(crafted, facts, _valid_entries())  # writes the base tar

    # Authored-fact guard: actual overhead = archive bytes minus the manifest
    # bytes minus the unique payload bytes; the lowered ceiling admits the
    # base tar itself with a small margin.
    manifest_len = len(json.dumps(facts, sort_keys=True, separators=(",", ":")).encode())
    payload_total = len(GLOSS_BYTES) + len(MEMO2_BYTES)
    actual_overhead = crafted.stat().st_size - manifest_len - payload_total
    assert actual_overhead > 0
    overhead_ceiling = actual_overhead + 2048
    monkeypatch.setattr(source_handoff, "CONTAINER_OVERHEAD_MAX_BYTES", overhead_ceiling)

    # Padding beyond the independent overhead ceiling while remaining far
    # below the total container budget (the manifest and payload allowances
    # stay at their defaults, so this distinguishes the two bounds).
    padding = 64 * 1024
    padded = tmp_path / "transfer" / "padded.tar"
    padded.write_bytes(crafted.read_bytes() + b"\x00" * padding)
    assert padded.stat().st_size - manifest_len - payload_total > overhead_ceiling
    max_container = (
        source_handoff.MANIFEST_MAX_BYTES
        + source_handoff.TOTAL_PAYLOAD_MAX_BYTES
        + overhead_ceiling
    )
    assert padded.stat().st_size < max_container

    snapshot = _canonical_snapshot(mreg_dir, mstore_dir)
    code = main(
        [
            "source-handoff",
            "import",
            str(mkb),
            "--bundle",
            str(padded),
            "--digest",
            hashlib.sha256(padded.read_bytes()).hexdigest(),
            "--revision",
            contribution,
            "--source-registry",
            str(mreg_dir),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2, captured
    assert "overhead" in captured.err
    assert _canonical_snapshot(mreg_dir, mstore_dir) == snapshot


# ---------------------------------------------------------------------------
# Delta-review D1/D2 regressions: physical-header size agreement and the
# terminal-EOF overhead invariant.
# ---------------------------------------------------------------------------

EMPTY_ID = "empty-note"
EMPTY_ENTITY = "entity:empty-note"
EMPTY_DIGEST = hashlib.sha256(b"").hexdigest()


def _empty_source_world(tmp_path: Path):
    """A contribution whose Source Reference Manifest binds a genuine
    zero-length source: the handoff contract admits size-zero versions."""
    repo = _init_repo(tmp_path / "contributor" / "repo")
    kb = _write_base_kb(repo)
    base = _commit(repo, "baseline revision")
    (kb / "concepts" / "empty-note.md").write_text(
        _managed_page("Empty Note", EMPTY_ENTITY, "note", EMPTY_ID)
    )
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        serialize_source_reference_manifest(
            SourceReferenceManifest(
                version=1,
                namespace=NAMESPACE,
                sources={MANUAL_ID: "active", MEMO_ID: "active", EMPTY_ID: "active"},
                bindings={
                    PRESS_ENTITY: {MANUAL_ID: MANUAL_DIGEST},
                    NOTE_ENTITY: {MEMO_ID: MEMO_DIGEST},
                    EMPTY_ENTITY: {EMPTY_ID: EMPTY_DIGEST},
                },
            )
        )
    )
    contribution = _commit(repo, "contribution binding the empty source")
    return repo, kb, base, contribution


def _normalized_header(name: str, size: int, type_flag: bytes) -> bytearray:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = 0o644
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    info.type = type_flag
    return bytearray(info.tobuf(tarfile.USTAR_FORMAT))


def _rechecksum(block: bytearray) -> bytes:
    """Recompute the documented tar checksum after patching a header field."""
    block[148:156] = b" " * 8
    block[148:156] = f"{sum(block):06o}\0 ".encode()
    return bytes(block)


def _pad_block(data: bytes) -> bytes:
    remainder = len(data) % 512
    return data + (b"\x00" * (512 - remainder) if remainder else b"")


def test_handoff_rejects_desynchronized_size_header(tmp_path, capsys, monkeypatch):
    """D1/F3: the physical guard and tarfile must agree where the next header
    starts — a NUL-led size field must never hide a forbidden record."""
    _repo, _kb, base, contribution = _empty_source_world(tmp_path)
    _clone, mkb, _mreg, mreg_dir, _mstore, mstore_dir = _maintainer_world(tmp_path)
    for variable in (SOURCE_REGISTRY_ENV_VAR, ARTIFACT_RETENTION_ENV_VAR):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv(SOURCE_STORE_ENV_VAR, str(mstore_dir))

    facts: dict[str, object] = {
        "schema_version": 1,
        "kind": "source-handoff",
        "transfer_id": "a" * 64,
        "namespace": NAMESPACE,
        "kb_subtree": "kb",
        "base_revision": base,
        "revision": contribution,
        "source_manifest_digest": hashlib.sha256(
            _git_bytes(_repo, "show", f"{contribution}:kb/{SOURCE_REFERENCE_MANIFEST_BASENAME}")
        ).hexdigest(),
        "bindings": [
            {
                "entity_id": EMPTY_ENTITY,
                "source_id": EMPTY_ID,
                "old_digest": None,
                "new_digest": EMPTY_DIGEST,
            }
        ],
        "versions": [
            {
                "source_id": EMPTY_ID,
                "content_hash": EMPTY_DIGEST,
                "size": 0,
                "content_type": None,
                "filename": None,
                "origin_created_at": ORIGIN_CREATED_AT,
                "intent": "new",
            },
            {
                "source_id": MANUAL_ID,
                "content_hash": MANUAL_DIGEST,
                "size": len(MANUAL_BYTES),
                "content_type": "application/pdf",
                "filename": "manual.pdf",
                "origin_created_at": ORIGIN_CREATED_AT,
                "intent": "reuse",
            },
        ],
    }
    manifest_json = json.dumps(facts, sort_keys=True, separators=(",", ":")).encode("utf-8")

    manifest_block = _normalized_header("manifest.json", len(manifest_json), tarfile.REGTYPE)
    # The desynchronized artifact header: tarfile's numeric parser stops at
    # the FIRST NUL byte (size 0); the field still carries octal digits after
    # it. Its checksum is correct per the documented algorithm.
    desync_block = _normalized_header(f"artifacts/{EMPTY_DIGEST}", 0, tarfile.REGTYPE)
    desync_block[124:136] = b"\x00" + b"00000001000"
    desync_block = bytearray(_rechecksum(desync_block))
    assert desync_block[124:136] == b"\x00" + b"00000001000"
    checksum_probe = bytearray(desync_block)
    checksum_probe[148:156] = b" " * 8
    assert int(desync_block[148:154].decode(), 8) == sum(checksum_probe)
    assert desync_block[156:157] == b"0"
    # The hidden PAX extension record (typeflag 'x', 512-byte zero body)
    # occupies exactly the region a size-512 misreading treats as body.
    x_block = _normalized_header("PaxHeader", 512, tarfile.XHDTYPE)
    assert x_block[156:157] == b"x"
    # The supplementary exact reference: MANUAL_ID/MANUAL_DIGEST is bound at
    # BOTH base and contribution (Git-derived intent "reuse"), so its
    # correctly declared regular payload after the hidden extension region
    # keeps the whole inventory honest while the hidden record stays hidden.
    manual_block = _normalized_header(
        f"artifacts/{MANUAL_DIGEST}", len(MANUAL_BYTES), tarfile.REGTYPE
    )

    crafted = tmp_path / "transfer" / "desync.tar"
    crafted.parent.mkdir(parents=True, exist_ok=True)
    crafted.write_bytes(
        bytes(manifest_block)
        + _pad_block(manifest_json)
        + bytes(desync_block)
        + bytes(x_block)
        + b"\x00" * 512  # the extension body a misreading mistakes for EOF
        + bytes(manual_block)
        + _pad_block(MANUAL_BYTES)
        + b"\x00" * 1024  # normal end-of-archive padding
    )
    digest = hashlib.sha256(crafted.read_bytes()).hexdigest()

    snapshot = _canonical_snapshot(mreg_dir, mstore_dir)
    code = main(
        [
            "source-handoff",
            "import",
            str(mkb),
            "--bundle",
            str(crafted),
            "--digest",
            digest,
            "--revision",
            contribution,
            "--source-registry",
            str(mreg_dir),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2, captured
    assert ("unsupported tar extension record" in captured.err) or ("plain octal" in captured.err)
    assert _canonical_snapshot(mreg_dir, mstore_dir) == snapshot


def test_handoff_checks_overhead_already_consumed_at_eof(tmp_path, capsys, monkeypatch):
    """D2/F4: bytes already consumed are checked when the dynamic overhead
    limit activates, and EOF must not skip the invariant."""
    import lumio_wiki.source_handoff as source_handoff

    world = _contributor_world(tmp_path)
    contribution, rebase = world["contribution"], world["rebase"]  # body-only range
    _clone, mkb, _mreg, mreg_dir, _mstore, mstore_dir = _maintainer_world(tmp_path)
    for variable in (SOURCE_REGISTRY_ENV_VAR, ARTIFACT_RETENTION_ENV_VAR):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv(SOURCE_STORE_ENV_VAR, str(mstore_dir))

    # Native Git blob guard: this actual range carries byte-identical Source
    # Reference Manifests (a body-only contribution), so empty binding and
    # version lists are the truthful selection for it.
    assert _git_bytes(
        world["repo"], "show", f"{contribution}:kb/{SOURCE_REFERENCE_MANIFEST_BASENAME}"
    ) == _git_bytes(world["repo"], "show", f"{rebase}:kb/{SOURCE_REFERENCE_MANIFEST_BASENAME}")

    facts = _handoff_manifest_facts(world["repo"], contribution, rebase)
    facts["bindings"] = []
    facts["versions"] = []
    manifest_json = json.dumps(facts, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest_len = len(manifest_json)

    # Authored-fact guard: a manifest header plus its block-padded JSON body,
    # then immediate EOF — actual overhead is at least the 512-byte header.
    padded = manifest_len + (-manifest_len % 512)
    overhead = 512 + padded - manifest_len
    assert overhead >= 512
    monkeypatch.setattr(source_handoff, "CONTAINER_OVERHEAD_MAX_BYTES", 128)

    crafted = tmp_path / "transfer" / "terminal.tar"
    crafted.parent.mkdir(parents=True, exist_ok=True)
    manifest_block = _normalized_header("manifest.json", manifest_len, tarfile.REGTYPE)
    crafted.write_bytes(bytes(manifest_block) + manifest_json + b"\x00" * (padded - manifest_len))
    digest = hashlib.sha256(crafted.read_bytes()).hexdigest()

    snapshot = _canonical_snapshot(mreg_dir, mstore_dir)
    code = main(
        [
            "source-handoff",
            "import",
            str(mkb),
            "--bundle",
            str(crafted),
            "--digest",
            digest,
            "--revision",
            rebase,
            "--source-registry",
            str(mreg_dir),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2, captured
    assert "overhead" in captured.err
    assert _canonical_snapshot(mreg_dir, mstore_dir) == snapshot
