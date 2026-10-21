"""Focused regression checks for plan 04 agent-facing seams."""

from __future__ import annotations

import hashlib
import json
import shlex
import shutil
from pathlib import Path

import lumio_wiki as lw
import msgspec
import pytest
from lumio_wiki.cli import main
from lumio_wiki.distiller import _build_distill_system_prompt
from lumio_wiki.records import EntityTypeDefinition, Ontology, PredicateDefinition

ROOT = Path(__file__).parents[3]
FIXTURES = ROOT / "tests" / "fixtures"


def _legacy_kb(tmp_path: Path, name: str = "kb") -> Path:
    root = tmp_path / name
    shutil.copytree(FIXTURES / "valid", root)
    return root


def test_page_machine_read_preserves_canonical_identity_and_bounds(tmp_path, capsys):
    root = _legacy_kb(tmp_path)
    canonical = (root / "overview.md").read_text(encoding="utf-8")

    assert main(["page", str(root), "Lumio Overview", "--raw", "--max-lines", "2", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["title"] == "Lumio Overview"
    assert result["path"] == "overview.md"
    assert result["content"] == "".join(canonical.splitlines(keepends=True)[:2])
    assert result["raw"] is True
    assert result["truncated"] is True
    assert result["omitted_lines"] > 0
    assert result["kb_location"] == str(root.resolve())

    assert main(["page", str(root), "Lumio Overview", "--max-lines", "1"]) == 0
    assert capsys.readouterr().out.startswith("---\n")


def test_machine_mutation_errors_are_stable_and_private(tmp_path, capsys):
    root = _legacy_kb(tmp_path)
    private_revision = "sk-private-invalid-revision"
    assert (
        main(
            [
                "publish",
                str(root),
                "--revision",
                private_revision,
                "--to",
                str(tmp_path / "published"),
                "--expected-current",
                "none",
                "--json",
            ]
        )
        == 1
    )
    result = json.loads(capsys.readouterr().out)
    assert result == {"ok": False, "error": {"code": "cli_error", "message": "command failed"}}
    assert private_revision not in capsys.readouterr().err
    assert not (tmp_path / "published").exists()


def test_copyable_actions_replay_original_kb(tmp_path, monkeypatch, capsys):
    first = _legacy_kb(tmp_path, "first")
    second = _legacy_kb(tmp_path, "second")
    from lumio_wiki.source_registry import SourceRegistry

    source_store = SourceRegistry(first / ".lumio" / "ingest" / "source-registry")
    source_store.register_source("lumio-overview", b"source bytes", filename="overview.md")

    assert main(["page", str(first), "Lumio Overview"]) == 0
    page_output = capsys.readouterr().out
    open_line = next(line for line in page_output.splitlines() if line.startswith("open:"))
    source_line = next(
        line for line in page_output.splitlines() if line.startswith("source-artifact:")
    )
    monkeypatch.setenv("LUMIO_KB_PATH", str(second))

    open_args = shlex.split(open_line.split(":", 1)[1].strip())
    assert main(open_args[1:]) == 0
    assert "# Lumio Overview" in capsys.readouterr().out

    source_args = shlex.split(source_line.split(":", 1)[1].strip())
    assert main(source_args[1:]) == 0
    source_output = capsys.readouterr().out
    assert "source_id:" in source_output
    assert "lumio-overview" in source_output
    assert str(first.resolve()) in source_line
    assert str(second.resolve()) not in source_line


def test_distiller_guidance_uses_current_kb_ontology():
    ontology = Ontology(
        entity_types={"service": EntityTypeDefinition(description="A deployed service.")},
        predicates={
            "depends-on": PredicateDefinition(
                subject_types=["service"],
                object_types=["service"],
                description="A runtime dependency.",
            )
        },
    )
    prompt = _build_distill_system_prompt(
        ["concepts"], ontology=ontology, authoring_mode="categorized"
    )

    assert "service — A deployed service." in prompt
    assert "depends-on" in prompt
    assert "A runtime dependency." in prompt
    assert "entity:<slug>" in prompt
    assert "accepted/disputed/superseded" in prompt
    assert "credentials" not in prompt


def test_real_anydoc_csv_cli_stages_reviewable_proposal(tmp_path, capsys, monkeypatch):
    pytest.importorskip("anydoc")
    from lumio_wiki.ingest import prepare_proposal_content

    from .test_entity_merge import _git_authoring_worktree

    csv = tmp_path / "records.csv"
    original = b"name,value\nalpha,1\n"
    csv.write_bytes(original)
    converted, provenance = prepare_proposal_content(original, "text/csv", csv.name)
    assert provenance.converted_by == "anydoc"
    assert provenance.source_hash == hashlib.sha256(original).hexdigest()
    converted_body = converted.split("---", 2)[2].strip()
    assert all(value in converted_body for value in ("name", "value", "alpha", "1"))

    root = tmp_path / "kb"
    assert main(["init", str(root)]) == 0
    control = root / "lumio.yaml"
    control.write_text(
        control.read_text().replace(
            "  entity_types:\n  predicates:",
            "  entity_types:\n    concept: {}\n  predicates:",
        )
    )
    (root / ".lumio-authoring.yaml").write_text(
        "version: 1\nnamespace: anydoc-csv-journey\nsources: {}\nbindings: {}\n"
    )
    _git_authoring_worktree(root)
    registry = tmp_path / "private-registry"
    store = tmp_path / "private-artifacts"
    monkeypatch.setenv("LUMIO_SOURCE_STORE", str(store))
    authored = tmp_path / "compiled.md"
    authored.write_text(
        "---\nid: entity:csv-records\ntitle: CSV Records\nentity_types: [concept]\n"
        "tags: [records]\nsummary: A small converted record table.\n"
        "category: references\ntype: record-table\n"
        "durability_rationale: Durable fixture table.\nlifecycle: draft\nvisibility: internal\n"
        "sources:\n  - id: csv-records\n    title: Original record table\n---\n\n"
        f"# CSV Records\n\n{converted_body}\n"
    )
    capsys.readouterr()
    # Managed ingest binds ORIGINAL CSV bytes; the real conversion above is preparation.
    assert (
        main(
            [
                "ingest",
                str(root),
                str(csv),
                "--compiled-page",
                str(authored),
                "--source-id",
                "csv-records",
                "--source-registry",
                str(registry),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "Ingested into the Git authoring worktree" in output
    kb, report = lw.load_knowledge_base(root)
    assert report.is_valid
    page = kb.lookup_by_title("CSV Records")[0]
    assert page.id == "entity:csv-records" and page.path.startswith("references/")
    assert converted_body in page.body
    manifest = msgspec.yaml.decode((root / ".lumio-authoring.yaml").read_bytes())
    assert (
        manifest["bindings"]["entity:csv-records"]["csv-records"]
        == hashlib.sha256(original).hexdigest()
    )
    assert not (root / ".lumio" / "ingest").exists()
    assert sorted(p.name for p in (root / ".lumio").iterdir()) == ["index"]
    assert registry.is_dir() and store.is_dir()
    assert not (root / csv.name).exists()
    for private_path in (csv, registry, store):
        assert str(private_path) not in page.body
        assert str(private_path) not in (root / ".lumio-authoring.yaml").read_text()


def test_packaged_source_commands_execute_in_order(tmp_path, capsys):

    from .test_git_authoring import _authored_ingest_page, _commit, _init_repo, _write_kb

    repo = _init_repo(tmp_path)
    root = _write_kb(repo)
    source = tmp_path / "source.txt"
    source.write_bytes(b"source")
    page = tmp_path / "page.md"
    page.write_text(_authored_ingest_page("example"))
    registry = tmp_path / "registry"
    assert (
        main(
            [
                "ingest",
                str(root),
                str(source),
                "--compiled-page",
                str(page),
                "--source-id",
                "example",
                "--source-registry",
                str(registry),
            ]
        )
        == 0
    )
    assert main(["validate", str(root)]) == 0
    revision = _commit(repo)
    destination = tmp_path / "published"
    args = [
        "publish",
        str(root),
        "--revision",
        revision,
        "--to",
        str(destination),
        "--expected-current",
        "none",
        "--source-registry",
        str(registry),
        "--json",
    ]
    capsys.readouterr()
    assert main(args) == 0
    review = json.loads(capsys.readouterr().out)
    assert not destination.exists()
    assert main([*args, "--confirm", review["review_digest"]]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["activated"] is True
    assert result["revision"] == revision


def test_protocol_denies_source_content_operational_authority():
    protocol = (Path(lw.__file__).parent / "data" / "skill" / "PROTOCOL.md").read_text(
        encoding="utf-8"
    )
    lower = protocol.lower()
    assert "untrusted data" in lower
    assert "authorize" in lower
    assert "never execute active" in lower
    assert "graph candidates" in lower or "citation existence" in lower


def test_readme_sample_validates_in_initialized_v2_kb():
    readme = (ROOT / "packages" / "lumio-wiki" / "README.md").read_text(encoding="utf-8")
    assert "entity:technology-stack" in readme
    assert 'entity_types: ["software-system"]' in readme
    assert "lumio-wiki validate ./knowledge-base" in readme
