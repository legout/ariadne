"""VD2: independently hand-written OOXML at the file/data-loss boundary."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import duckdb
import pytest

from ariadne.spreadsheet_import import SpreadsheetImportError, import_workbook


def _write_hand_ooxml(
    path: Path,
    *,
    cached: bool = True,
    oversized: bool = False,
    override_a: str | None = None,
    override_b: str | None = None,
) -> None:
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
    if override_a is not None:
        sheet_a = override_a
    if override_b is not None:
        sheet_b = override_b
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


def _sheet_xml(source: Path, sheet_number: int) -> str:
    with zipfile.ZipFile(source) as archive:
        return archive.read(f"xl/worksheets/sheet{sheet_number}.xml").decode()


def _single_column_sheet(data_rows: int) -> str:
    rows = "".join(
        f'<row r="{row}"><c r="A{row}"><v>1</v></c></row>' for row in range(2, data_rows + 2)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:A{data_rows + 1}"/><sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>amount</t></is></c></row>
    {rows}
  </sheetData>
</worksheet>"""


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
            "SELECT amount, __ariadne_source_row FROM a ORDER BY __ariadne_source_row"
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

    mismatched = tmp_path / "mismatched-dimension.xlsx"
    _write_hand_ooxml(
        mismatched,
        override_a=_sheet_xml(source, 1).replace('dimension ref="A1:A4"', 'dimension ref="A1:A2"'),
    )
    mismatch_output = tmp_path / "mismatch-output"
    with pytest.raises(SpreadsheetImportError, match="actual worksheet extent") as mismatch:
        import_workbook(mismatched, sheets=["A"], output=mismatch_output)
    assert mismatch.value.code == "inconsistent_dimensions"
    assert list(mismatch_output.iterdir()) == []

    sparse_source = tmp_path / "sparse.xlsx"
    sparse_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:C2"/><sheetData>
    <row r="1">
      <c r="A1" t="inlineStr"><is><t>amount</t></is></c>
      <c r="C1" t="inlineStr"><is><t>note</t></is></c>
    </row>
    <row r="2"><c r="A2"><v>11</v></c><c r="C2"><v>12</v></c></row>
  </sheetData>
</worksheet>"""
    _write_hand_ooxml(sparse_source, override_a=sparse_xml)
    sparse = import_workbook(sparse_source, sheets=["A"], output=tmp_path / "sparse-output")
    sparse_sheet = sparse["sheets"][0]
    assert sparse_sheet["actual_dimension"] == "A1:C2"
    assert sparse_sheet["source_rows"] == [2]
    assert sparse_sheet["nonempty_cell_count"] == 4
    assert [column["header_cell"] for column in sparse_sheet["columns"]] == ["A1", "B1", "C1"]
    assert sparse_sheet["columns"][1]["source_header"] is None
    assert sparse_sheet["columns"][1]["name"] == "column_2"
    assert sparse_sheet["columns"][1]["interpreted_type"] == "VARCHAR"
    sparse_connection = duckdb.connect(sparse["artifact_path"], read_only=True)
    try:
        assert sparse_connection.execute(
            "SELECT amount, column_2, note, __ariadne_source_row FROM a"
        ).fetchall() == [(11, None, 12, 2)]
    finally:
        sparse_connection.close()

    combined = tmp_path / "combined-over-limit.xlsx"
    many_rows = _single_column_sheet(100_000)
    _write_hand_ooxml(combined, override_a=many_rows, override_b=many_rows)
    combined_output = tmp_path / "combined-output"
    with pytest.raises(SpreadsheetImportError, match="whole conversion") as combined_refusal:
        import_workbook(combined, sheets=["A", "B"], output=combined_output)
    assert combined_refusal.value.code == "selected_cells_too_large"
    assert list(combined_output.iterdir()) == []

    out_of_order_source = tmp_path / "out-of-order.xlsx"
    out_of_order_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:B2"/><sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>amount</t></is></c></row>
    <row r="2">
      <c r="A2"><v>10</v></c>
      <c r="C2"><f>10+20</f></c>
      <c r="B2"><v>20</v></c>
    </row>
  </sheetData>
</worksheet>"""
    _write_hand_ooxml(out_of_order_source, override_a=out_of_order_xml)
    out_of_order_output = tmp_path / "out-of-order-output"
    with pytest.raises(SpreadsheetImportError, match="B2") as out_of_order:
        import_workbook(out_of_order_source, sheets=["A"], output=out_of_order_output)
    assert out_of_order.value.code == "out_of_order_cells"
    assert list(out_of_order_output.iterdir()) == []

    trailing_source = tmp_path / "trailing-blank-header.xlsx"
    trailing_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:B2"/><sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>amount</t></is></c></row>
    <row r="2"><c r="A2"><v>11</v></c><c r="B2"><v>12</v></c></row>
  </sheetData>
</worksheet>"""
    _write_hand_ooxml(trailing_source, override_a=trailing_xml)
    trailing = import_workbook(trailing_source, sheets=["A"], output=tmp_path / "trailing-output")
    trailing_sheet = trailing["sheets"][0]
    assert trailing_sheet["actual_dimension"] == "A1:B2"
    assert trailing_sheet["source_rows"] == [2]
    assert trailing_sheet["nonempty_cell_count"] == 3
    assert [column["header_cell"] for column in trailing_sheet["columns"]] == ["A1", "B1"]
    assert trailing_sheet["columns"][1]["source_header"] is None
    assert trailing_sheet["columns"][1]["name"] == "column_2"
    trailing_connection = duckdb.connect(trailing["artifact_path"], read_only=True)
    try:
        assert trailing_connection.execute(
            "SELECT amount, column_2, __ariadne_source_row FROM a"
        ).fetchall() == [(11, 12, 2)]
    finally:
        trailing_connection.close()

    attribute_free_source = tmp_path / "attribute-free.xlsx"
    attribute_free_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:B2"/><sheetData>
    <row>
      <c t="inlineStr"><is><t>amount</t></is></c>
      <c t="inlineStr"><is><t>note</t></is></c>
    </row>
    <row><c><v>11</v></c><c><v>12</v></c></row>
  </sheetData>
</worksheet>"""
    _write_hand_ooxml(attribute_free_source, override_a=attribute_free_xml)
    attribute_free = import_workbook(
        attribute_free_source, sheets=["A"], output=tmp_path / "attribute-free-output"
    )
    attribute_free_sheet = attribute_free["sheets"][0]
    assert attribute_free_sheet["actual_dimension"] == "A1:B2"
    assert attribute_free_sheet["source_rows"] == [2]
    assert attribute_free_sheet["nonempty_cell_count"] == 4
    assert [column["header_cell"] for column in attribute_free_sheet["columns"]] == ["A1", "B1"]
    attribute_free_connection = duckdb.connect(attribute_free["artifact_path"], read_only=True)
    try:
        assert attribute_free_connection.execute(
            "SELECT amount, note, __ariadne_source_row FROM a"
        ).fetchall() == [(11, 12, 2)]
    finally:
        attribute_free_connection.close()

    shared_follower_source = tmp_path / "shared-follower-implicit.xlsx"
    shared_follower_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:A3"/><sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>amount</t></is></c></row>
    <row r="2">
      <c r="A2"><f t="shared" ref="A2:A3" si="0">10+20</f><v>30</v></c>
    </row>
    <row r="3"><c><f t="shared" si="0"/><v>30</v></c></row>
  </sheetData>
</worksheet>"""
    _write_hand_ooxml(shared_follower_source, override_a=shared_follower_xml)
    shared_follower_output = tmp_path / "shared-follower-output"
    with pytest.raises(SpreadsheetImportError, match="explicit r") as shared_follower:
        import_workbook(shared_follower_source, sheets=["A"], output=shared_follower_output)
    assert shared_follower.value.code == "shared_formula_implicit_reference"
    assert list(shared_follower_output.iterdir()) == []

    shared_master_source = tmp_path / "shared-master-implicit.xlsx"
    shared_master_xml = shared_follower_xml.replace(
        '<c r="A2"><f t="shared"', '<c><f t="shared"'
    )
    _write_hand_ooxml(shared_master_source, override_a=shared_master_xml)
    shared_master_output = tmp_path / "shared-master-output"
    with pytest.raises(SpreadsheetImportError, match="explicit r") as shared_master:
        import_workbook(shared_master_source, sheets=["A"], output=shared_master_output)
    assert shared_master.value.code == "shared_formula_implicit_reference"
    assert list(shared_master_output.iterdir()) == []
