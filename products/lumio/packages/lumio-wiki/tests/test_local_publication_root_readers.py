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


def _advance(root: Path, version: str) -> None:
    """Admit ``version`` (a copy of the current one) and move the pointer to it."""
    src = root / "versions" / "rev1"
    shutil.copytree(src, root / "versions" / version)
    manifest = msgspec.json.decode(
        (src / MANIFEST_OBJECT).read_bytes(), type=type(build_published_manifest("x", "y", {}))
    )
    (root / "versions" / version / MANIFEST_OBJECT).write_bytes(
        msgspec.json.encode(msgspec.structs.replace(manifest, version=version))
    )
    (root / "current.json").write_bytes(msgspec.json.encode(S3Pointer(version=version)))


def test_published_version_is_refused_on_a_worktree_and_when_empty(tmp_path, capsys):
    kb = tmp_path / "wt"
    shutil.copytree(CATEGORIZED, kb)
    for cmd in ("health", "status", "mcp", "validate"):
        assert cli.main([cmd, str(kb), "--published-version", "rev1"]) == 2, cmd
    root = _publication_root(tmp_path)
    assert cli.main(["mcp", str(root), "--published-version", ""]) == 2
    assert "traceback" not in capsys.readouterr().err.lower()


def test_health_on_a_published_root_reads_the_versions_graph(tmp_path, capsys):
    root = _publication_root(tmp_path)
    kb = cli._open_local_published_snapshot(root).knowledge_base
    kb.materialize_graph(root / "versions" / "rev1" / "derived")
    capsys.readouterr()

    assert cli.main(["health", str(root)]) == 0
    out = capsys.readouterr().out
    assert "graph_materialized:  True" in out and "graph_fresh:         True" in out
    assert "--rebuild" not in out
    assert cli.main(["status", str(root), "--json"]) == 0
    assert '"graph_fresh": true' in capsys.readouterr().out


def test_unmaterialized_published_root_gives_no_rebuild_advice(tmp_path, capsys):
    root = _publication_root(tmp_path)
    capsys.readouterr()
    assert cli.main(["health", str(root)]) == 0
    assert "--rebuild" not in capsys.readouterr().out
    assert cli.main(["status", str(root)]) == 0
    assert "--rebuild" not in capsys.readouterr().out


def test_mcp_status_projects_local_published_kind_to_filesystem(tmp_path):
    from lumio_wiki import mcp_server

    root = _publication_root(tmp_path)
    snapshot = cli._open_local_published_snapshot(root)
    assert mcp_server.status_rows(snapshot)["location"] == {"kind": "filesystem"}


def test_worktree_with_a_stray_current_json_still_loads(tmp_path, capsys):
    kb = tmp_path / "wt"
    shutil.copytree(CATEGORIZED, kb)
    (kb / "current.json").write_text('{"note": "unrelated"}')
    assert cli.main(["validate", str(kb)]) == 0
    assert cli.main(["health", str(kb)]) == 0
    assert "mode:                categorized" in capsys.readouterr().out


def test_page_open_command_replays_a_historical_version(tmp_path, capsys):
    import json
    import shlex

    root = _publication_root(tmp_path)
    _advance(root, "rev2")
    capsys.readouterr()

    old = ["page", str(root), "Lumio Overview", "--published-version", "rev1", "--json"]
    assert cli.main(old) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["published_version"] == "rev1"
    assert cli.main(shlex.split(data["open_command"])[1:]) == 0
    capsys.readouterr()

    assert cli.main(["search", str(root), "Lumio", "--json"]) == 0
    hit = json.loads(capsys.readouterr().out)["results"][0]
    assert hit["published_version"] == "rev2"
    assert cli.main(shlex.split(hit["open_command"])[1:]) == 0
