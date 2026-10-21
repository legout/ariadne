"""Managed host-Distiller ingest (issue #149) on the native worktree route.

G4 (spec 0008 §7): the persisted staged-proposal route is retired. The ONE
deep operation that binds an original raw Knowledge Source
(PDF/DOCX/HTML/Markdown/TXT) and a host-agent-authored Compiled Page now
writes ordinary files plus exact source bindings into the selected Git
authoring worktree through ``ingest_into_worktree``. Covers the retained
issue #149 acceptance criteria on that route: the single journey, per-format
provenance + immutable Source Version, identical-byte reuse, the
authored-page source-id contract, compound provenance, and private raw
isolation. Legacy staging semantics (changed-byte staging refusal, proposal
inspect, staged publish) were retired with the pipeline; changed-byte
registration and publication privacy are pinned natively in
``test_git_authoring.py``.

The retired-source case is pinned by ``test_git_authoring``'s retirement
suite: a retired managed source cannot carry supporting bindings
(``validate_source_references``), and native retirement is a Git manifest
edit.
"""

from __future__ import annotations

from pathlib import Path

import lumio_wiki as lw
import pytest
from lumio_wiki.git_authoring import ingest_into_worktree
from lumio_wiki.ingest import ManagedIngestError
from lumio_wiki.source_references import SourceReferenceManifest
from lumio_wiki.source_registry import SourceRegistry

ROOT = Path(__file__).parents[3]
FIXTURES = ROOT / "tests" / "lumio" / "fixtures" / "valid"

# (filename, content_type, expected converter) for AC2. No converter runs —
# managed ingest derives the converter NAME from routing, so the [documents]
# extra is never required and fake raw bytes suffice for every format.
FORMAT_PROVENANCE = [
    ("2025-impact-report.pdf", "application/pdf", "liteparse"),
    ("2025-impact-report.docx", None, "anydoc"),
    ("2025-impact-report.html", "text/html", "markitdown"),
    ("2025-impact-report.md", "text/markdown", "markdown"),
    ("2025-impact-report.txt", "text/plain", "text"),
]

CONTROL_V2 = """\
version: 2
mode: "categorized"
categories:
  - name: reports
ontology:
  entity_types:
    report: {}
  predicates: {}
  redirects: {}
"""


def _kb(tmp_path: Path):
    """A manifest-adopted Git authoring KB (native managed ingest route)."""
    from test_git_authoring import _init_repo, _write_kb

    repo = _init_repo(tmp_path)
    root = _write_kb(
        repo,
        manifest=SourceReferenceManifest(
            version=1, namespace="urn:uuid:1a2b3c4d-managed-0000-0000-managedkb0001"
        ),
        control=CONTROL_V2,
        pages={"reports/seed-report.md": _authored_page("seed-report", title="Seed Report")},
    )
    kb, report = lw.load_knowledge_base(root)
    assert report.is_valid, report
    return kb


def _registry(tmp_path: Path) -> SourceRegistry:
    return SourceRegistry(tmp_path / "registry")


def _authored_page(
    source_id: str, *, title: str = "Impact Report", entity: str | None = None
) -> str:
    return (
        "---\n"
        f'id: "entity:{entity or source_id}"\n'
        f'title: "{title}"\n'
        "entity_types:\n  - report\n"
        "category: reports\n"
        'type: "impact report"\n'
        'durability_rationale: "The impact report documents durable findings."\n'
        "aliases: []\n"
        'tags:\n  - "report"\n'
        'summary: "Authored by the host agent from the original source."\n'
        'lifecycle: "draft"\n'
        'visibility: "internal"\n'
        "sources:\n"
        f'  - id: "{source_id}"\n'
        f'    title: "{source_id} source"\n'
        "synthetic: false\n"
        "---\n\n"
        "# Impact Report\n\n"
        "Body authored by the host coding agent from the original source.\n"
    )


def test_managed_ingest_binds_source_and_authored_page_into_one_worktree_edit(
    tmp_path: Path,
):
    kb = _kb(tmp_path)
    registry = _registry(tmp_path)
    raw = b"%PDF-1.4 original impact report bytes"

    result = ingest_into_worktree(
        kb.root,
        raw,
        "application/pdf",
        "2025-impact-report.pdf",
        "annual-impact-report",
        _authored_page("annual-impact-report"),
        source_registry=registry,
    )

    assert result.source_id == "annual-impact-report"
    assert len(result.page_paths) == 1
    # The authored Markdown — not distilled text — is the written page content.
    written = (Path(kb.root) / result.page_paths[0]).read_text(encoding="utf-8")
    assert "Body authored by the host coding agent" in written
    # ONE worktree edit carries the exact binding into the manifest.
    assert Path(result.manifest_path).is_file()
    assert "annual-impact-report" in Path(result.manifest_path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AC2 — per-format provenance + immutable Source Version identity.
# ---------------------------------------------------------------------------


def test_managed_ingest_never_requires_the_documents_extra(tmp_path: Path):
    # No document converter runs (the host agent authored the page). The
    # processor is never invoked, so a PDF/DOCX/HTML source reaches the
    # worktree without LiteParse/MarkItDown installed.
    kb = _kb(tmp_path)
    registry = _registry(tmp_path)
    for filename, content_type, _ in FORMAT_PROVENANCE:
        if content_type is None:
            continue
        # Slug-safe UNIQUE id per format (entity ids forbid raw dots and
        # two formats must not collapse onto one page destination).
        source_id = "src-" + filename.replace(".", "-").replace(" ", "-").lower()
        result = ingest_into_worktree(
            kb.root,
            b"raw",
            content_type,
            filename,
            source_id,
            _authored_page(source_id, title=f"Page {source_id}"),
            source_registry=registry,
        )
        assert result.source_id == source_id
        assert result.page_paths


def test_managed_ingest_repeats_with_identical_bytes_reusing_source_version(
    tmp_path: Path,
):
    kb = _kb(tmp_path)
    registry = _registry(tmp_path)
    raw = b"%PDF-1.4 identical bytes"

    first = ingest_into_worktree(
        kb.root,
        raw,
        "application/pdf",
        "r.pdf",
        "annual-impact-report",
        _authored_page("annual-impact-report"),
        source_registry=registry,
    )
    # The retry registers the SAME bytes under a SECOND authored page (the
    # first edit is still uncommitted; the dirty guard correctly refuses
    # overwriting it, so the reuse contract is pinned across distinct pages).
    second = ingest_into_worktree(
        kb.root,
        raw,
        "application/pdf",
        "r.pdf",
        "annual-impact-report",
        _authored_page(
            "annual-impact-report",
            title="Impact Report Follow-Up",
            entity="annual-impact-report-follow-up",
        ),
        source_registry=registry,
    )

    source = registry.get("annual-impact-report")
    assert len(source.versions) == 1  # no duplicate Source Version
    # The identical retry converges on the same content-addressed version
    # with truthful reuse disclosure (D5).
    assert first.content_hash == second.content_hash == source.versions[0].content_hash
    assert second.registration == "reused"


# ---------------------------------------------------------------------------
# Authored-page source-id contract — a missing/mismatched id blocks the write.
# ---------------------------------------------------------------------------


def test_managed_ingest_missing_source_id_blocks_the_write(tmp_path: Path):
    kb = _kb(tmp_path)
    registry = _registry(tmp_path)
    page = _authored_page("some-other-id")  # does NOT cite the chosen id

    with pytest.raises(ManagedIngestError, match=r"sources\[\].id"):
        ingest_into_worktree(
            kb.root,
            b"raw",
            "text/plain",
            "r.txt",
            "annual-impact-report",
            page,
            source_registry=registry,
        )
    # Nothing was registered or written.
    assert registry.list() == []
    assert not any(page.title == "Impact Report" for page in kb.pages)


def test_managed_ingest_compound_revision_may_retain_additional_sources(tmp_path: Path):
    # The chosen source_id only needs to appear once; compound revisions may
    # retain additional existing Sources on the same page.
    kb = _kb(tmp_path)
    registry = _registry(tmp_path)
    page = (
        "---\n"
        'id: "entity:compound-page"\n'
        'title: "Compound Page"\n'
        "entity_types:\n  - report\n"
        "category: reports\n"
        'type: "compound report"\n'
        'durability_rationale: "Compound provenance is durable."\n'
        'tags:\n  - "report"\n'
        'summary: "Compound provenance page."\n'
        'lifecycle: "draft"\n'
        'visibility: "internal"\n'
        "sources:\n"
        '  - id: "existing-source"\n'
        '    title: "existing"\n'
        '  - id: "annual-impact-report"\n'
        '    title: "new source"\n'
        "---\n\n# Compound Page\n\nBody.\n"
    )

    result = ingest_into_worktree(
        kb.root,
        b"raw",
        "application/pdf",
        "r.pdf",
        "annual-impact-report",
        page,
        source_registry=registry,
    )
    written = (Path(kb.root) / result.page_paths[0]).read_text(encoding="utf-8")
    assert "existing-source" in written
    assert "annual-impact-report" in written


# ---------------------------------------------------------------------------
# AC3 — the raw source is isolated in private state, never under the KB.
# ---------------------------------------------------------------------------


def test_managed_ingest_keeps_raw_source_in_private_state_not_under_kb_root(tmp_path: Path):
    kb = _kb(tmp_path)
    registry = _registry(tmp_path)
    raw = b"%PDF-1.4 private raw bytes"

    ingest_into_worktree(
        kb.root,
        raw,
        "application/pdf",
        "2025-impact-report.pdf",
        "annual-impact-report",
        _authored_page("annual-impact-report"),
        source_registry=registry,
    )

    # The registry lives OUTSIDE the Knowledge Base root and retains only
    # identity/version hashes — not the raw bytes.
    assert registry.root.is_dir()
    assert not (Path(kb.root) / "source-registry").exists()
    # No raw bytes are written under the KB root (page-discovery risk).
    for path in Path(kb.root).rglob("*"):
        if path.is_file():
            assert raw not in path.read_bytes(), f"raw bytes leaked into KB: {path}"
