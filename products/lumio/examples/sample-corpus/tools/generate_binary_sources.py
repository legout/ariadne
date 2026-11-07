"""Generate the binary files of the Lumio sample corpus.

Regenerates ``orders.parquet`` (DuckDB, from the committed ``orders.csv``),
``catalog.xlsx`` (openpyxl plus a stdlib pass that injects stored cached
values into the ``pricing`` formula cells; the ``draft_totals`` sheet keeps
its formula without a cache on purpose), ``supplier-brief.pdf`` (a minimal
valid PDF written with the standard library, cross-reference offsets
computed programmatically) and ``installation-note.docx`` (minimal OOXML
assembled with ``zipfile``).

The committed text files (``orders.csv``, ``orders.json``,
``operations-notes.md``) are inputs, never outputs. Run from the repository
venv that provides ``duckdb`` and, for XLSX, the ``ariadne-data[spreadsheets]``
extra (``openpyxl``). Expected values are hand-set in the corpus README and
must never be copied from converter output.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

CORPUS = Path(__file__).resolve().parents[1]

# Fixed archive timestamps keep the generated OOXML containers byte-reproducible.
ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)
CORE_TIMESTAMP = "2026-01-01T00:00:00Z"

# Hand-computed cached results for catalog.xlsx!pricing (list_price = cost
# marked up by the margin): 32*1.25=40, 8*1.5=12, 210*1.4=294, 160*1.3=208.
PRICING_CACHE: dict[str, str] = {"E2": "40", "E3": "12", "E4": "294", "E5": "208"}

PDF_LINES = [
    "Harbor Point Supplier Brief",
    "",
    "Panels and inverters arrive at dock 4 on weekdays.",
    "The duty technician signs the delivery note within 30 minutes.",
]

DOCX_BODY_PARAGRAPHS = [
    "Mount the beacon mast at least 12 meters from the fuel store.",
    "Kester Logistics delivers spare bulbs with the next panel shipment.",
]


def generate_parquet() -> Path:
    import duckdb

    path = CORPUS / "orders.parquet"
    duckdb.execute(
        f"""
        COPY (
            SELECT * FROM read_csv('{CORPUS / "orders.csv"}', header = true, columns = {{
                'order_id': 'BIGINT',
                'order_date': 'DATE',
                'region': 'VARCHAR',
                'customer': 'VARCHAR',
                'product_line': 'VARCHAR',
                'quantity': 'BIGINT',
                'unit_price_eur': 'DECIMAL(10,2)',
                'net_amount_eur': 'DECIMAL(10,2)',
            }})
        ) TO '{path}' (FORMAT PARQUET)
        """
    )
    return path


def _sheet_path(archive: zipfile.ZipFile, workbook: str, rels: str, sheet: str) -> str:
    """Resolve a sheet name to its worksheet part via workbook.xml and its rels."""
    rid = re.search(rf'<sheet[^>]*name="{sheet}"[^>]*r:id="([^"]+)"', workbook)
    if rid is None:  # attribute order differs in some writers
        rid = re.search(rf'<sheet[^>]*r:id="([^"]+)"[^>]*name="{sheet}"', workbook)
    assert rid is not None, f"sheet {sheet!r} not found in workbook.xml"
    target = re.search(rf'<Relationship[^>]*Id="{rid.group(1)}"[^>]*Target="([^"]+)"', rels)
    if target is None:
        target = re.search(rf'<Relationship[^>]*Target="([^"]+)"[^>]*Id="{rid.group(1)}"', rels)
    assert target is not None, f"relationship {rid.group(1)!r} not found"
    return "xl/" + target.group(1).removeprefix("/xl/").lstrip("/")


def _inject_cached_values(sheet_xml: str) -> str:
    for cell, value in PRICING_CACHE.items():
        # openpyxl writes formulas with an EMPTY <v></v>; replace that element
        # in place so each cached cell carries exactly one value element.
        pattern = rf'(<c r="{cell}"[^>]*>)(<f>[^<]*</f>)(<v\s*/>|<v></v>)'
        replacement = rf"\1\2<v>{value}</v>"
        sheet_xml, count = re.subn(pattern, replacement, sheet_xml)
        assert count == 1, f"formula cell {cell} not found exactly once"
    return sheet_xml


def generate_xlsx() -> Path:
    from openpyxl import Workbook

    path = CORPUS / "catalog.xlsx"
    workbook = Workbook()
    del workbook["Sheet"]  # drop the default empty sheet
    pricing = workbook.create_sheet("pricing")
    pricing.append(["item_code", "description", "unit_cost_eur", "margin_pct", "list_price_eur"])
    for row in (
        ("P-100", "Solar panel 400 W", 32.00, 25, "=C2*(1+D2/100)"),
        ("P-200", "Mounting rail 2 m", 8.00, 50, "=C3*(1+D3/100)"),
        ("I-300", "Inverter 5 kW", 210.00, 40, "=C4*(1+D4/100)"),
        ("B-400", "Battery 10 kWh", 160.00, 30, "=C5*(1+D5/100)"),
    ):
        pricing.append(row)
    draft = workbook.create_sheet("draft_totals")
    draft.append(["label", "base_eur", "extra_eur", "total_eur"])
    draft.append(("draft", 1, 2, "=B2+C2"))  # no stored cached value, on purpose
    workbook.save(path)

    # openpyxl writes formulas without cached results and stamps docProps with
    # wall-clock times (the writer force-sets `modified` at save); rewrite both
    # in place so the committed workbook stays byte-reproducible.
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    core = entries["docProps/core.xml"].decode()
    for field in ("created", "modified"):
        core, count = re.subn(
            rf"(<dcterms:{field}[^>]*>)[^<]*(</dcterms:{field}>)",
            rf"\g<1>{CORE_TIMESTAMP}\g<2>",
            core,
        )
        assert count == 1, f"core property {field} not found exactly once"
    entries["docProps/core.xml"] = core.encode()
    sheet_part = _sheet_path(
        archive=None,  # type: ignore[arg-type]
        workbook=entries["xl/workbook.xml"].decode(),
        rels=entries["xl/_rels/workbook.xml.rels"].decode(),
        sheet="pricing",
    )
    entries[sheet_part] = _inject_cached_values(entries[sheet_part].decode()).encode()
    _write_zip(path, entries)
    return path


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name, date_time=ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)


def generate_pdf() -> Path:
    def build(objects: list[bytes]) -> bytes:
        out = bytearray(b"%PDF-1.4\n")
        offsets: list[int] = []
        for number, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
        start = len(out)
        out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
        for offset in offsets:
            out += f"{offset:010d} 00000 n \n".encode()
        out += (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n"
        ).encode()
        return bytes(out)

    text = b"BT /F1 12 Tf 72 720 Td 16 TL\n"
    text += b"\n".join(f"({line}) Tj T*".encode() for line in PDF_LINES)
    text += b"\nET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(text), text),
    ]
    path = CORPUS / "supplier-brief.pdf"
    path.write_bytes(build(objects))
    return path


def generate_docx() -> Path:
    part = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        "<w:body>\n"
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
        "<w:r><w:t>Beacon Installation Note</w:t></w:r></w:p>\n"
    )
    for paragraph in DOCX_BODY_PARAGRAPHS:
        part += f"<w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>\n"
    part += "<w:sectPr/>\n</w:body>\n</w:document>"
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '<Default Extension="xml" ContentType="application/xml"/>\n'
        '<Override PartName="/word/document.xml" ContentType='
        '"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>\n'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>\n'
        "</Relationships>"
    )
    path = CORPUS / "installation-note.docx"
    _write_zip(
        path,
        {
            "[Content_Types].xml": content_types.encode(),
            "_rels/.rels": rels.encode(),
            "word/document.xml": part.encode(),
        },
    )
    return path


def main() -> None:
    for expected_name, generate in (
        ("orders.parquet", generate_parquet),
        ("catalog.xlsx", generate_xlsx),
        ("supplier-brief.pdf", generate_pdf),
        ("installation-note.docx", generate_docx),
    ):
        written = generate()
        if written.name != expected_name:
            raise SystemExit(f"unexpected output {written.name}, expected {expected_name}")
        print(f"wrote {written.relative_to(CORPUS)}")


if __name__ == "__main__":
    main()
