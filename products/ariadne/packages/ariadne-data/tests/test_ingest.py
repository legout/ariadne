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
        (".docx", "firecrawl-anydoc"),
        (".pptx", "firecrawl-anydoc"),
        (".xlsx", "firecrawl-anydoc"),
        (".html", "markitdown[docx]"),
        (".doc", "firecrawl-anydoc"),
        (".rtf", "firecrawl-anydoc"),
        (".epub", "firecrawl-anydoc"),
        (".csv", "firecrawl-anydoc"),
        (".odt", "firecrawl-anydoc"),
        (".ods", "firecrawl-anydoc"),
        (".odp", "firecrawl-anydoc"),
        (".xls", "firecrawl-anydoc"),
        (".docm", "firecrawl-anydoc"),
        (".pptm", "firecrawl-anydoc"),
        (".ppsx", "firecrawl-anydoc"),
        (".xlsm", "firecrawl-anydoc"),
        (".xlsb", "firecrawl-anydoc"),
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
        "<w:body>"
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Renewal policy</w:t></w:r></w:p>'
        "<w:p><w:r><w:t>Renewal policy from the handbook</w:t></w:r></w:p>"
        '<w:p><w:pPr><w:pStyle w:val="ListBullet"/><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/>'
        "</w:numPr></w:pPr><w:r><w:t>Churned rows excluded</w:t></w:r></w:p>"
        "<w:tbl>"
        "<w:tr><w:tc><w:p><w:r><w:t>Status</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>Treatment</w:t></w:r></w:p></w:tc></w:tr>"
        "<w:tr><w:tc><w:p><w:r><w:t>Status</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>zaehlt</w:t></w:r></w:p></w:tc></w:tr>"
        "</w:tbl>"
        "</w:body>"
        "</w:document>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '<Override PartName="/word/numbering.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.wordprocessingml.numbering+xml"/></Types>',
        )
        w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        zf.writestr(
            "word/_rels/document.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{rel}/styles" Target="styles.xml"/>'
            f'<Relationship Id="rId2" Type="{rel}/numbering" Target="numbering.xml"/>'
            "</Relationships>",
        )
        zf.writestr(
            "word/styles.xml",
            f'<w:styles {w}><w:style w:type="paragraph" w:styleId="Heading1">'
            '<w:name w:val="heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>'
            "</w:styles>",
        )
        zf.writestr(
            "word/numbering.xml",
            f'<w:numbering {w}><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0">'
            '<w:numFmt w:val="bullet"/><w:lvlText w:val="-"/></w:lvl></w:abstractNum>'
            '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>',
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


def test_docx_conversion_via_anydoc(tmp_path):
    pytest.importorskip("anydoc")
    from ariadne.ingest import _convert

    text = _convert(_minimal_docx(tmp_path / "handbook.docx"))
    assert "Renewal policy from the handbook" in text
    assert any(line.startswith("# ") and "Renewal policy" in line for line in text.splitlines())
    assert "Churned rows excluded" in text
    assert "| Status | zaehlt |" in text


def test_xlsx_conversion_via_anydoc(tmp_path):
    pytest.importorskip("anydoc")
    from ariadne.ingest import _convert

    path = tmp_path / "book.xlsx"
    ct = "application/vnd.openxmlformats-officedocument.spreadsheetml"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'

    def sheet(rows):
        body = "".join(
            "<row>" + "".join(f'<c t="inlineStr"><is><t>{v}</t></is></c>' for v in row) + "</row>"
            for row in rows
        )
        return f"<worksheet {ns}><sheetData>{body}</sheetData></worksheet>"

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/xl/workbook.xml" ContentType="{ct}.sheet.main+xml"/>'
            f'<Override PartName="/xl/worksheets/sheet1.xml" ContentType="{ct}.worksheet+xml"/>'
            f'<Override PartName="/xl/worksheets/sheet2.xml" ContentType="{ct}.worksheet+xml"/>'
            "</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        zf.writestr(
            "xl/workbook.xml",
            f'<workbook {ns} xmlns:r="{rel}"><sheets>'
            '<sheet name="Accounts" sheetId="1" r:id="rId1"/>'
            '<sheet name="Notes" sheetId="2" r:id="rId2"/></sheets></workbook>',
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/>'
            f'<Relationship Id="rId2" Type="{rel}/worksheet" Target="worksheets/sheet2.xml"/>'
            "</Relationships>",
        )
        zf.writestr(
            "xl/worksheets/sheet1.xml",
            sheet([["Account", "Status"], ["Acme", "ACTIVE"], ["Globex", "CHURNED"]]),
        )
        zf.writestr("xl/worksheets/sheet2.xml", sheet([["Remark"], ["second sheet"]]))
    text = _convert(path)
    assert "## Accounts" in text and "## Notes" in text
    assert "| Account | Status |" in text and "| Globex | CHURNED |" in text
    assert "second sheet" in text


def test_anydoc_never_requests_hosted_ocr(tmp_path, monkeypatch):
    anydoc = pytest.importorskip("anydoc")
    from ariadne.ingest import _ConversionError, _convert

    calls = []

    def fake(path, **kwargs):
        calls.append(kwargs)
        raise type("NeedsOcrError", (Exception,), {})("scanned")

    monkeypatch.setattr(anydoc, "to_markdown", fake)
    doc = tmp_path / "scan.docx"
    doc.write_bytes(b"x")
    with pytest.raises(_ConversionError, match=r"scan\.docx.*needs OCR"):
        _convert(doc)
    assert calls == [{}]


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
