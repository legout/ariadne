"""VD2: independently hand-written OOXML at the file/data-loss boundary."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import duckdb
import pytest

from ariadne.spreadsheet_import import SpreadsheetImportError, import_workbook


def _write_hand_ooxml(path: Path, *, cached: bool = True, oversized: bool = False) -> None:
    """Write the fixture XML directly; openpyxl is deliberately not a fixture oracle."""
    formula_cache = "<v>7</v>" if cached else ""
    sheet_a = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:A4"/><sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>amount</t></is></c></row>
    <row r="2"><c r="A2"><v>10</v></c></row>
    <row r="3"><c r="A3"><v>20</v></c></row>
    <row r="4"><c r="A4"><f>10+20</f>{formula_cache}</c></row>
  </sheetData>
</worksheet>"""
    sheet_b = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:A2"/><sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>amount</t></is></c></row>
    <row r="2"><c r="A2"><v>999</v></c></row>
  </sheetData>
</worksheet>"""
    entries = {
        "[Content_Types].xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>""",
        "_rels/.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="xl/workbook.xml"/>
</Relationships>""",
        "xl/workbook.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="A" sheetId="1" r:id="rId1"/>
    <sheet name="B" sheetId="2" r:id="rId2"/>
  </sheets>
</workbook>""",
        "xl/_rels/workbook.xml.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    Target="worksheets/sheet2.xml"/>
</Relationships>""",
        "xl/worksheets/sheet1.xml": sheet_a,
        "xl/worksheets/sheet2.xml": sheet_b,
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, text in entries.items():
            archive.writestr(name, text)
        if oversized:
            archive.writestr(
                "xl/oversized.bin",
                b"x" * (25 * 1024 * 1024),
                compress_type=zipfile.ZIP_STORED,
            )


def test_workbook_stored_values_and_refresh_are_truthful(tmp_path: Path) -> None:
    source = tmp_path / "known.xlsx"
    _write_hand_ooxml(source)
    output = tmp_path / "derived"

    imported = import_workbook(source, sheets=["A"], output=output)

    # Hand-derived oracle: the stored cache is deliberately 7, not 10+20.
    assert imported["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert imported["reused"] is False
    assert [sheet["name"] for sheet in imported["sheets"]] == ["A"]
    sheet = imported["sheets"][0]
    assert sheet["table"] == "a"
    assert sheet["row_count"] == 3
    assert sheet["columns"][0]["source_header"] == "amount"
    assert sheet["columns"][0]["interpreted_type"] == "BIGINT"
    assert sheet["formula_cells"][0]["cell"] == "A4"
    assert sheet["formula_cells"][0]["formula"] == "10+20"
    assert sheet["formula_cells"][0]["cached_value"] == 7
    assert sheet["formula_cells"][0]["cache_freshness"] == "unknown"
    artifact = Path(imported["artifact_path"])
    connection = duckdb.connect(str(artifact), read_only=True)
    try:
        assert connection.execute(
            'SELECT amount, __ariadne_source_row FROM a ORDER BY __ariadne_source_row'
        ).fetchall() == [(10, 2), (20, 3), (7, 4)]
        assert connection.execute("SELECT SUM(amount) FROM a").fetchone() == (37,)
        assert connection.execute(
            "SELECT table_name FROM information_schema.tables ORDER BY table_name"
        ).fetchall() == [("a",)]
    finally:
        connection.close()

    reused = import_workbook(source, sheets=["A"], output=output)
    assert reused["reused"] is True
    assert reused["selection_identity"] == imported["selection_identity"]

    missing = tmp_path / "missing-cache.xlsx"
    _write_hand_ooxml(missing, cached=False)
    missing_output = tmp_path / "missing-output"
    with pytest.raises(SpreadsheetImportError, match="A4") as refused:
        import_workbook(missing, sheets=["A"], output=missing_output)
    assert refused.value.code == "missing_formula_cache"
    assert list(missing_output.iterdir()) == []

    prior_bytes = artifact.read_bytes()
    prior_entries = {path.name for path in output.iterdir()}
    with pytest.raises(SpreadsheetImportError, match="A4"):
        import_workbook(missing, sheets=["A"], output=output)
    assert artifact.read_bytes() == prior_bytes
    assert {path.name for path in output.iterdir()} == prior_entries

    oversized = tmp_path / "oversized.xlsx"
    _write_hand_ooxml(oversized, oversized=True)
    oversized_output = tmp_path / "oversized-output"
    with pytest.raises(SpreadsheetImportError) as too_large:
        import_workbook(oversized, sheets=["A"], output=oversized_output)
    assert too_large.value.code == "input_too_large"
    assert list(oversized_output.iterdir()) == []
