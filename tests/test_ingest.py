"""Standalone document ingestion (spec rev 8 §8.19, ADR-0009).

LLM responses are fixture-mocked (no network), the same machinery as
tests/test_author.py; the per-type gate runs for real (the author's
_page_contract_errors over assembled pages). Real converter invocations are
gated by pytest.importorskip so the suite passes with or without the
[documents] extra installed.
"""

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.ingest import (  # noqa: E402
    _CONVERTERS,
    _NATIVE_SUFFIXES,
    MAX_RETRIES,
    ingest,
    main,
)
from ariadne.init import main as init_main  # noqa: E402

MODEL = "test-model"


def page_entry(**overrides) -> dict:
    """One gate-clean policy page entry (the shape the system prompt asks for)."""
    entry = {
        "folder": "policies",
        "name": "churned-arr-not-expansion",
        "type": "policy",
        "title": "Churned ARR is not expansion",
        "description": "CHURNED renewal rows are excluded from expansion totals.",
        "tags": ["policy", "arr", "ingest"],
        "body": "# Churned ARR is not expansion\n\nCHURNED rows record lost ARR.",
    }
    entry.update(overrides)
    return entry


def response(*entries: dict) -> str:
    return json.dumps({"pages": list(entries)})


def make_doc(tmp_path: Path, suffix: str = ".md", text: str | None = None) -> Path:
    doc = tmp_path / f"notes{suffix}"
    doc.write_text(
        text or "# Renewal notes\n\nCHURNED rows must never be summed into expansion totals.\n",
        encoding="utf-8",
    )
    return doc


def run_ingest(tmp_path: Path, doc: Path, responses: list[str], monkeypatch):
    """ingest() with a replaying fake LLM; returns (staging, staged, errors, calls)."""
    monkeypatch.setenv("OPENAI_MODEL", MODEL)
    calls: list[list[dict]] = []

    def complete(messages):
        calls.append(messages)
        return responses[min(len(calls), len(responses)) - 1]

    staging = tmp_path / "staging"
    staged, errors = ingest([doc], staging_dir=staging, complete=complete)
    return staging, staged, errors, calls


def front_of(page: Path) -> dict:
    return yaml.safe_load(page.read_text(encoding="utf-8").split("---")[1])


# --- (a) md ingestion: typed page, mechanical provenance ----------------------


def test_md_ingestion_stages_typed_page_with_provenance(tmp_path, monkeypatch):
    doc = make_doc(tmp_path)
    staging, staged, errors, calls = run_ingest(
        tmp_path, doc, [response(page_entry())], monkeypatch
    )

    assert errors == [] and len(calls) == 1  # passed on the first attempt
    page = staging / "context_layer" / "policies" / "churned-arr-not-expansion.md"
    assert staged == [page] and page.is_file()

    front = front_of(page)
    assert front["type"] == "policy"
    assert front["status"] == "draft"
    assert front["generated"]["by"] == f"ariadne-ingest:{MODEL}"
    assert front["generated"]["at"]  # ISO stamp present
    (source,) = front["sources"]
    assert source["id"] == hashlib.sha256(doc.read_bytes()).hexdigest()[:12]
    assert source["resource"] == str(doc.resolve())
    assert source["title"] == doc.name
    assert "CHURNED" in page.read_text(encoding="utf-8")  # body survived assembly


def test_multi_page_response_stages_every_page(tmp_path, monkeypatch):
    doc = make_doc(tmp_path)
    entries = [
        page_entry(),
        page_entry(
            folder="tables",
            name="renewals",
            type="table",
            tags=["table", "renewals"],
            grain={
                "primary_key": ["account_id", "renewal_date"],
                "cardinality_enforcement": "STRICT_1_TO_1",
            },
            body="# renewals\n\nOne row per renewal event.",
        ),
    ]
    staging, staged, errors, _ = run_ingest(tmp_path, doc, [response(*entries)], monkeypatch)

    assert errors == []
    assert {p.parent.name for p in staged} == {"policies", "tables"}
    front = front_of(staging / "context_layer" / "tables" / "renewals.md")
    assert front["type"] == "table"
    assert front["grain"]["primary_key"] == ["account_id", "renewal_date"]


# --- (b) contract violations: retry loop, nothing partially staged ------------


def test_contract_violation_retries_then_stages_nothing(tmp_path, monkeypatch):
    doc = make_doc(tmp_path)
    # every round proposes a metrics page — author-owned, never ingestable
    staging, staged, errors, calls = run_ingest(
        tmp_path, doc, [response(page_entry(folder="metrics", type="metric"))], monkeypatch
    )

    assert len(calls) == 1 + MAX_RETRIES  # first attempt + ≤2 retries, then stop
    assert errors and any("author-owned" in error for error in errors)
    assert not (staging / "context_layer").exists()  # nothing ever touched staging
    feedback = calls[1][-1]["content"]
    assert "Contract violations" in feedback  # error feedback loop like the author


def test_frontmatter_gate_violation_is_fed_back_and_repaired(tmp_path, monkeypatch):
    doc = make_doc(tmp_path)
    bad = page_entry(tags=[])  # gate: policy page requires 'tags'
    staging, staged, errors, calls = run_ingest(
        tmp_path, doc, [response(bad), response(page_entry())], monkeypatch
    )

    assert len(calls) == 2  # round 1 rejected, round 2 recovered
    assert any("'tags'" in error for error in errors[0:1]) or errors == []
    assert staged and front_of(staged[0])["status"] == "draft"
    assert not any("review_needed" in p.read_text() for p in staged)


def test_gate_rejects_table_page_without_grain(tmp_path, monkeypatch):
    doc = make_doc(tmp_path)
    bad = page_entry(folder="tables", name="renewals", type="table", tags=["table"])
    _, staged, errors, _ = run_ingest(tmp_path, doc, [response(bad)], monkeypatch)

    assert staged == []  # nothing staged...
    assert errors and any("grain" in error for error in errors)  # ...violation named


def test_index_and_log_names_never_stage(tmp_path, monkeypatch):
    doc = make_doc(tmp_path)
    _, staged, errors, _ = run_ingest(
        tmp_path, doc, [response(page_entry(name="index"))], monkeypatch
    )
    assert staged == [] and any("bookkeeping" in error for error in errors)


# --- (c) unclassifiable -> references/ + ingest tag ---------------------------


def test_unclassifiable_lands_in_references_with_ingest_tag(tmp_path, monkeypatch):
    doc = make_doc(tmp_path, text="Meeting musings with no schema and no rule.\n")
    entry = page_entry(
        folder="references",
        name="cs-weekly-musings",
        type="reference",
        tags=["ingest", "notes"],
        body="# CS weekly musings\n\nBackground context worth keeping.",
    )
    staging, staged, errors, _ = run_ingest(tmp_path, doc, [response(entry)], monkeypatch)

    assert errors == []
    page = staging / "context_layer" / "references" / "cs-weekly-musings.md"
    assert staged == [page]
    front = front_of(page)
    assert front["type"] == "reference" and "ingest" in front["tags"]


# --- (d) name collisions suffix atomically -----------------------------------


def test_name_collision_suffixes_never_overwrites(tmp_path, monkeypatch):
    doc = make_doc(tmp_path)
    staging = tmp_path / "staging"
    existing = staging / "context_layer" / "policies" / "churned-arr-not-expansion.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("---\ntype: policy\n---\n\nkeep me\n", encoding="utf-8")

    staging2, staged, errors, _ = run_ingest(
        tmp_path, doc, [response(page_entry())], monkeypatch
    )

    assert errors == []
    assert staged == [staging / "context_layer" / "policies" / "churned-arr-not-expansion-2.md"]
    assert "keep me" in existing.read_text(encoding="utf-8")  # original untouched


# --- (e) unsupported extension + missing extra name the extra ----------------


def test_unsupported_extension_error_names_support_and_extra(tmp_path, monkeypatch):
    doc = make_doc(tmp_path, suffix=".pages")
    staging, staged, errors, calls = run_ingest(
        tmp_path, doc, [response(page_entry())], monkeypatch
    )

    assert staged == [] and calls == []  # rejected before any LLM call
    (error,) = errors
    assert "[documents]" in error and "uv pip install" in error
    assert ".md" in error and ".pdf" in error  # the supported set is named


def test_missing_pdf_converter_error_names_requirement(tmp_path, monkeypatch):
    doc = make_doc(tmp_path, suffix=".pdf", text="unused")
    monkeypatch.setenv("OPENAI_MODEL", MODEL)
    monkeypatch.setitem(sys.modules, "liteparse", None)  # import raises ImportError
    staged, errors = ingest([doc], staging_dir=tmp_path / "staging", complete=lambda _m: "")

    assert staged == []
    assert any("liteparse" in error and "[documents]" in error for error in errors)


def test_missing_docx_converter_error_names_markitdown_extra(tmp_path, monkeypatch):
    doc = make_doc(tmp_path, suffix=".docx", text="unused")
    monkeypatch.setenv("OPENAI_MODEL", MODEL)
    monkeypatch.setitem(sys.modules, "markitdown", None)
    staged, errors = ingest([doc], staging_dir=tmp_path / "staging", complete=lambda _m: "")

    assert staged == []
    assert any("markitdown[docx]" in error for error in errors)


def test_ingest_never_writes_outside_staging(tmp_path, monkeypatch):
    doc = make_doc(tmp_path)
    with pytest.raises(ValueError, match="repo root|served"):
        ingest([doc], staging_dir=Path.cwd(), complete=lambda _m: response(page_entry()))
    assert not list(tmp_path.rglob("context_layer"))


def test_model_stamp_uses_env_loaded_by_the_first_call(tmp_path, monkeypatch):
    """Regression (live run): the default endpoint loads ARIADNE_ENV inside the
    first LLM call — the stamp must be read after that, not before."""
    doc = make_doc(tmp_path)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    def complete(messages):
        monkeypatch.setenv("OPENAI_MODEL", "late-model")  # what _load_env does
        return response(page_entry())

    staged, errors = ingest([doc], staging_dir=tmp_path / "staging", complete=complete)
    assert errors == []
    assert front_of(staged[0])["generated"]["by"] == "ariadne-ingest:late-model"


# --- (f) init scaffolds data/docs/ --------------------------------------------


def test_init_scaffolds_data_docs(tmp_path):
    target = tmp_path / "proj"
    assert init_main([str(target)]) == 0
    assert (target / "data" / "docs").is_dir()
    assert init_main([str(target)]) == 0  # idempotent re-run still succeeds
    assert (target / "data" / "docs").is_dir()


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


def test_dispatch_table_exactly_matches_native_suffixes():
    assert set(_CONVERTERS) | set(_NATIVE_SUFFIXES) == {
        ".md", ".txt", ".pdf", ".docx", ".pptx", ".xlsx", ".html", ".doc",
        ".rtf", ".epub", ".csv", ".odt", ".ods", ".odp", ".xls",
    }


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


# --- CLI ----------------------------------------------------------------------


def test_cli_stages_and_reports(tmp_path, monkeypatch, capsys):
    import ariadne.ingest as ingest_module

    doc = make_doc(tmp_path)
    monkeypatch.setenv("OPENAI_MODEL", MODEL)
    monkeypatch.setattr(ingest_module, "_default_complete", lambda _m: response(page_entry()))
    code = main([str(doc), "--staging", str(tmp_path / "staging")])

    assert code == 0
    out = capsys.readouterr().out
    assert "staged:" in out and "[policy]" in out
    assert (tmp_path / "staging" / "context_layer" / "policies").is_dir()


def test_cli_fails_on_unsupported_extension(tmp_path, capsys):
    doc = make_doc(tmp_path, suffix=".pages")
    assert main([str(doc)]) == 1  # the console script raises SystemExit(1) on this
    assert "[documents]" in capsys.readouterr().err


def test_cli_accepts_ignored_db_flag(tmp_path, monkeypatch):
    import ariadne.ingest as ingest_module

    doc = make_doc(tmp_path)
    monkeypatch.setenv("OPENAI_MODEL", MODEL)
    monkeypatch.setattr(ingest_module, "_default_complete", lambda _m: response(page_entry()))
    assert main([str(doc), "--db", "data/demo.db", "--staging", str(tmp_path / "s")]) == 0
