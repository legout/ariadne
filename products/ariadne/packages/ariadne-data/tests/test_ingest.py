"""Converter dispatch/real conversions for the retained ariadne.ingest seam.

C6 (spec0035 §6, G3 disposition): document onboarding is Lumio-native; the
retired ``ariadne-ingest`` orchestration (``ingest``/``reconcile_ingest``/
``Reconciliation``/``main``/``MAX_RETRIES``, the candidate-discovery walks over
``context.list_pages``/``read_page``/``search_pages`` and the CLI) is REMOVED,
so every test constructing its scenario exclusively through that orchestration
is deleted with it. The live document-digest-binding and credential-refusal
invariants are covered natively (test_git_authoring's changed-evidence
staleness journey; test_git_proposals' credential-bearing edit refusal through
the shared proposals seam). KEPT: the ``ariadne init`` operator-input
scaffolding contract and the converter dispatch table + real conversions
(``_convert``/``_CONVERTERS``/``_NATIVE_SUFFIXES``) with their retained
callers in ``ariadne.authoring_inputs``. (The ``ariadne init`` scaffolding
contract rides its own module coverage.)
"""

import sys
import zipfile
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.ingest import (  # noqa: E402
    _CONVERTERS,
)


def make_doc(tmp_path: Path, suffix: str = ".md", text: str | None = None) -> Path:
    doc = tmp_path / f"notes{suffix}"
    doc.write_text(
        text or "# Renewal notes\n\nCHURNED rows must never be summed into expansion totals.\n",
        encoding="utf-8",
    )
    return doc


# --- (g) converter dispatch table + real conversions behind importorskip ------


@pytest.mark.parametrize(
    ("suffix", "requirement"),
    [
        (".pdf", "liteparse"),
        (".docx", "markitdown[docx]"),
        (".pptx", "markitdown[docx]"),
        (".xlsx", "markitdown[docx]"),
        (".html", "markitdown[docx]"),
        (".doc", "firecrawl-anydoc"),
        (".rtf", "firecrawl-anydoc"),
        (".epub", "firecrawl-anydoc"),
        (".csv", "firecrawl-anydoc"),
        (".odt", "firecrawl-anydoc"),
        (".ods", "firecrawl-anydoc"),
        (".odp", "firecrawl-anydoc"),
        (".xls", "firecrawl-anydoc"),
    ],
)
def test_dispatch_table_maps_suffix_to_requirement(suffix, requirement):
    assert suffix in _CONVERTERS
    assert _CONVERTERS[suffix][1] == requirement


def test_native_conversion_is_plain_read(tmp_path):
    from ariadne.ingest import _convert

    doc = make_doc(tmp_path)
    assert _convert(doc) == doc.read_text(encoding="utf-8")


def _minimal_pdf(path: Path) -> Path:
    lines = [
        b"%PDF-1.4",
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj",
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj",
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj",
        b"4 0 obj<</Length 60>>stream",
        b"BT /F1 24 Tf 72 700 Td (Renewals policy notes) Tj ET",
        b"endstream",
        b"endobj",
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj",
        b"trailer<</Root 1 0 R>>",
    ]
    path.write_bytes(b"\n".join(lines))
    return path


def test_pdf_conversion_via_liteparse(tmp_path):
    pytest.importorskip("liteparse")
    from ariadne.ingest import _convert

    text = _convert(_minimal_pdf(tmp_path / "doc.pdf"))
    assert "Renewals policy notes" in text


def _minimal_docx(path: Path) -> Path:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>Renewal policy from the handbook</w:t></w:r></w:p></w:body>"
        "</w:document>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        zf.writestr("word/document.xml", document)
    return path


def test_docx_conversion_via_markitdown(tmp_path):
    pytest.importorskip("markitdown")
    from ariadne.ingest import _convert

    text = _convert(_minimal_docx(tmp_path / "handbook.docx"))
    assert "Renewal policy from the handbook" in text


def test_html_conversion_via_markitdown(tmp_path):
    pytest.importorskip("markitdown")
    from ariadne.ingest import _convert

    doc = tmp_path / "page.html"
    doc.write_text(
        "<html><body><h1>Fiscal calendar</h1><p>FY ends in <b>June</b>.</p></body></html>"
    )
    text = _convert(doc)
    assert "Fiscal calendar" in text and "June" in text


def test_rtf_conversion_via_firecrawl_anydoc(tmp_path):
    pytest.importorskip("anydoc")
    from ariadne.ingest import _convert

    doc = tmp_path / "memo.rtf"
    doc.write_text(r"{\rtf1\ansi Churned ARR is not booked ARR.}")
    assert "Churned ARR" in _convert(doc)
