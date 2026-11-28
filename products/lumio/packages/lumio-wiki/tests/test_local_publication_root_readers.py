"""Readers resolve a local publication root to its current Published Version (#206)."""

from __future__ import annotations

import shutil
from pathlib import Path

import msgspec
import pytest
from lumio_wiki import cli
from lumio_wiki.knowledge_base import _FilesystemKbSource, canonical_content, fingerprint_sources
from lumio_wiki.s3_location import MANIFEST_OBJECT, S3Pointer, build_published_manifest

pytest.importorskip("obstore")

CATEGORIZED = Path(__file__).parents[3] / "tests" / "fixtures" / "categorized_kb"


def _publication_root(tmp_path: Path, version: str = "rev1") -> Path:
    root = tmp_path / "published"
    version_dir = root / "versions" / version
    shutil.copytree(CATEGORIZED, version_dir)
    content = canonical_content(_FilesystemKbSource(version_dir.resolve()))
    manifest = build_published_manifest(version, fingerprint_sources(version_dir).digest, content)
    (version_dir / MANIFEST_OBJECT).write_bytes(msgspec.json.encode(manifest))
    (root / "current.json").write_bytes(msgspec.json.encode(S3Pointer(version=version)))
    (root / ".lumio-publication").mkdir()
    return root


def test_every_reader_resolves_the_root_to_its_current_version(tmp_path, capsys):
    root = _publication_root(tmp_path)
    capsys.readouterr()

    assert cli.main(["validate", str(root)]) == 0
    assert cli.main(["health", str(root)]) == 0
    out = capsys.readouterr().out
    assert "mode:                categorized" in out or "mode:                legacy" not in out
    assert "valid:               True" in out
    assert cli.main(["status", str(root), "--json"]) == 0
    assert '"validation_valid": true' in capsys.readouterr().out
    assert cli.main(["search", str(root), "a"]) == 0
    assert cli.main(["health", str(root), "--published-version", "rev1"]) == 0
    assert cli.main(["health", str(root), "--published-version", "nope"]) != 0


def test_mcp_accepts_the_publication_root(tmp_path, monkeypatch):
    from lumio_wiki import mcp_server

    root = _publication_root(tmp_path)
    served = []

    class _Stub:
        def __init__(self, location):
            served.append(location)

        def run(self):
            pass

    monkeypatch.setattr(mcp_server, "build_server", _Stub)
    assert cli.main(["mcp", str(root)]) == 0
    assert served[0].read_pointer() == "rev1"
