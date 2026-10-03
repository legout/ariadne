"""Standalone document ingestion (spec rev 8 §8.19, ADR-0009).

LLM responses are fixture-mocked (no network), the same machinery as
tests/test_author.py; the per-type gate runs for real (the author's
_page_contract_errors over assembled pages). Real converter invocations are
gated by pytest.importorskip so the suite passes with or without the
[documents] extra installed.
"""

import base64
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
    Reconciliation,
    ingest,
    main,
    reconcile_ingest,
)
from ariadne.init import main as init_main  # noqa: E402
from ariadne.promote import promote  # noqa: E402

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
    """Spec 0010 §3 (issue #41): a physical table page may carry UNKNOWN
    Grain — an absent grain block stages fine — while a DECLARED but
    malformed grain block (missing cardinality_enforcement) is still a named
    violation."""
    doc = make_doc(tmp_path)
    unknown = page_entry(folder="tables", name="renewals", type="table", tags=["table"])
    _, staged, errors, _ = run_ingest(tmp_path, doc, [response(unknown)], monkeypatch)
    assert staged != [] and errors == []  # unknown Grain stages honestly

    malformed = page_entry(
        folder="tables",
        name="renewals2",
        type="table",
        tags=["table"],
        grain={"primary_key": ["id"]},
    )
    _, staged, errors, _ = run_ingest(tmp_path, doc, [response(malformed)], monkeypatch)
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


# --- (c2) K2: structured References survive ingestion (issue #42) ------------


def _reference_entry(**overrides) -> dict:
    """One gate-clean structured Reference entry: the order-number term with
    its allowlisted aliases/bindings/declaration (the allowlist shape the K2
    system prompt describes)."""
    payload = base64.urlsafe_b64encode(
        json.dumps(["orders", None, "orders", "orders"], separators=(",", ":")).encode()
    ).decode().rstrip("=")
    entry = page_entry(
        folder="references",
        name="order-number",
        type="reference",
        title="Order number",
        description="The shared order-number concept of the orders store.",
        tags=["reference", "term"],
        body=(
            "# Order number\n\nThe store-scoped local number and the concatenated "
            "global identity."
        ),
    )
    entry["aliases"] = ["order number concept"]
    entry["ariadne"] = {
        "version": 1,
        "reference_role": "term",
        "representations": [
            {
                "id": "global-order-number",
                "aliases": ["global order number"],
                "fields": [
                    {
                        "resource": f"ariadne://table/{payload}",
                        "column": "global_order_number",
                    }
                ],
                "scope": [],
            }
        ],
        "mappings": [],
    }
    entry.update(overrides)
    return entry


def test_ingest_preserves_reference_bindings_without_fabricating_measurements(
    tmp_path, monkeypatch
):
    """K2 (issue #42, spec 0010 §3/AC10): ordinary ingestion PRESERVES the
    allowlisted aliases/bindings/structured declaration with the ACTUAL input
    document's provenance — the previous _assemble silently dropped them — and
    the shared per-type gate refuses a fabricated confirmation/measurement
    claim, feeding it back instead of staging anything."""
    doc = make_doc(
        tmp_path,
        text="# Order numbers\n\nA global order number concatenates the store prefix "
        "and the local number; both representations are documented here.\n",
    )
    staging, staged, errors, calls = run_ingest(
        tmp_path, doc, [response(_reference_entry())], monkeypatch
    )

    assert errors == []
    page = staging / "context_layer" / "references" / "order-number.md"
    assert staged == [page]
    front = front_of(page)
    # the structured declaration survived staging verbatim (the metadata-loss
    # path: _assemble used to drop everything but its fixed frontmatter keys)
    assert front["aliases"] == ["order number concept"]
    extension = front["ariadne"]
    assert extension["version"] == 1 and extension["reference_role"] == "term"
    (representation,) = extension["representations"]
    assert representation["id"] == "global-order-number"
    assert representation["fields"][0]["column"] == "global_order_number"
    assert representation["fields"][0]["resource"].startswith("ariadne://table/")
    # provenance is the ACTUAL input document — mechanically attached, never
    # authored — and no measurement/approval state was fabricated
    assert front["sources"] == [
        {
            "id": hashlib.sha256(doc.read_bytes()).hexdigest()[:12],
            "resource": str(doc.resolve()),
            "title": doc.name,
        }
    ]
    assert "status" in front and front["status"] == "draft"
    assert set(front) == {
        "type",
        "status",
        "title",
        "description",
        "tags",
        "sources",
        "generated",
        "aliases",
        "ariadne",
    }
    # the resolver reads the staged page: the preserved declaration resolves
    from ariadne.context import resolve_term
    resolved = resolve_term([(staging / "context_layer", True)], "global order number")
    assert [match["representation"] for match in resolved["matches"]] == [
        "global-order-number"
    ]
    assert resolved["matches"][0]["draft"] is True

    # a fabricated confirmation claim is REFUSED: the gate feeds it back and
    # nothing is staged (the strict mapping allowlist, shared with Git
    # validation — a document never confirms itself)
    forged = _reference_entry()
    forged["ariadne"] = {
        **forged["ariadne"],
        "mappings": [
            {
                "id": "local-to-global",
                "family": "prefix",
                "from": "global-order-number",
                "to": "global-order-number",
                "claim": "asserted",
                "source_ids": [],
                "confirmed": True,
                "tested": 999,
            }
        ],
    }
    second = tmp_path / "second"
    second.mkdir()
    staging2, staged2, errors2, _calls = run_ingest(
        second, make_doc(second, text="second document\n"), [response(forged)], monkeypatch
    )
    assert staged2 == [] and errors2, "a fabricated claim must never stage"
    assert any("unsupported field(s)" in error for error in errors2)
    assert any("'confirmed'" in error for error in errors2)


def test_non_reference_ariadne_blocks_are_refused_not_preserved(tmp_path, monkeypatch):
    """Spec 0010 §3: the ``ariadne`` extension belongs to References. A table
    or policy entry carrying one — fabricated authority/measurements included
    — is REFUSED at staging (nothing stages while it stands), never laundered
    by silently preserving or dropping the block; the repaired entry without
    it stages clean."""
    doc = make_doc(tmp_path)
    smuggled = page_entry(
        folder="tables",
        name="renewals",
        type="table",
        tags=["table", "renewals"],
        body="# renewals\n\nOne row per renewal event.",
    )
    smuggled["ariadne"] = {"confirmed": True, "observations": {"tested": 999}}
    clean = {key: value for key, value in smuggled.items() if key != "ariadne"}

    # the block standing on a non-Reference: refused every round, nothing staged
    staging, staged, errors, calls = run_ingest(tmp_path, doc, [response(smuggled)], monkeypatch)
    assert staged == []
    assert len(calls) == 1 + MAX_RETRIES  # fed back each round, never staged
    assert any("belongs to References" in error for error in errors)
    assert not (staging / "context_layer").exists()

    # the fed-back violation is repairable: the entry without the block stages
    repair = tmp_path / "repair"
    repair.mkdir()
    _, staged2, errors2, _ = run_ingest(
        repair, make_doc(repair), [response(smuggled), response(clean)], monkeypatch
    )
    assert errors2 == [] and len(staged2) == 1
    assert "ariadne" not in front_of(staged2[0])  # never preserved on a table


def test_mapping_citing_the_input_document_stages_and_validates(tmp_path, monkeypatch):
    """The document's staged footnote id is core-owned: the prompt material
    carries the ACTUAL staged citation id, the model cites the input document
    with the explicit ``@document`` token, and _assemble binds the token
    mechanically to the real digest id — a documented asserted mapping
    survives ingestion and validates (not only empty-mappings documents)."""
    doc = make_doc(
        tmp_path,
        text="# Order numbers\n\nA global order number concatenates the store "
        "prefix and the local number; the document states the correspondence.\n",
    )
    entry = _reference_entry()
    table_resource_uri = entry["ariadne"]["representations"][0]["fields"][0]["resource"]
    entry["ariadne"]["representations"].append(
        {
            "id": "local-order-number",
            "aliases": ["local order number"],
            "fields": [{"resource": table_resource_uri, "column": "local_order_number"}],
            "scope": [],
        }
    )
    entry["ariadne"]["mappings"] = [
        {
            "id": "documented-correspondence",
            "family": "prefix",
            "from": "local-order-number",
            "to": "global-order-number",
            "claim": "asserted",
            "source_ids": ["@document"],
        }
    ]
    digest = hashlib.sha256(doc.read_bytes()).hexdigest()[:12]
    staging, staged, errors, calls = run_ingest(tmp_path, doc, [response(entry)], monkeypatch)

    assert errors == []
    assert staged == [staging / "context_layer" / "references" / "order-number.md"]
    # the prompt material named the ACTUAL staged citation id (core-owned)
    assert digest in calls[0][1]["content"]
    # the token was bound mechanically — the staged mapping cites the digest
    front = front_of(staged[0])
    assert front["ariadne"]["mappings"][0]["source_ids"] == [digest]
    assert "@document" not in staged[0].read_text(encoding="utf-8")
    # and the staged page validates end to end: the resolver serves the mapping
    from ariadne.context import resolve_term

    resolved = resolve_term([(staging / "context_layer", True)], "global order number")
    [mapping] = resolved["matches"][0]["mappings"]
    assert mapping["claim"] == "asserted" and mapping["source_ids"] == [digest]


# --- (d) name collisions suffix atomically -----------------------------------


def test_name_collision_suffixes_never_overwrites(tmp_path, monkeypatch):
    doc = make_doc(tmp_path)
    staging = tmp_path / "staging"
    existing = staging / "context_layer" / "policies" / "churned-arr-not-expansion.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("---\ntype: policy\n---\n\nkeep me\n", encoding="utf-8")

    staging2, staged, errors, _ = run_ingest(tmp_path, doc, [response(page_entry())], monkeypatch)

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
    # also block a submodule an earlier test may really have imported: a
    # surviving liteparse.parser entry would defeat the parent-module block
    monkeypatch.setitem(sys.modules, "liteparse.parser", None)
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
        ".md",
        ".txt",
        ".pdf",
        ".docx",
        ".pptx",
        ".xlsx",
        ".html",
        ".doc",
        ".rtf",
        ".epub",
        ".csv",
        ".odt",
        ".ods",
        ".odp",
        ".xls",
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


# --- (h) staging symlink refusal (init.py component-walk discipline) ---------


def test_symlinked_context_layer_refuses_to_stage_anything(tmp_path, monkeypatch):
    """staging/context_layer -> external dir: an attacker-planted link must
    receive nothing — staged pages would otherwise bypass the promotion gate."""
    doc = make_doc(tmp_path)
    staging = tmp_path / "staging"
    outside = tmp_path / "context_layer"  # e.g. the served layer
    outside.mkdir()
    staging.mkdir()
    link = staging / "context_layer"
    link.symlink_to(outside, target_is_directory=True)

    _, staged, errors, _ = run_ingest(tmp_path, doc, [response(page_entry())], monkeypatch)

    assert staged == []  # nothing staged
    assert not list(outside.iterdir())  # nothing written outside staging
    (error,) = errors
    assert "symlink" in error and str(link) in error  # offending path named


def test_symlinked_subfolder_component_refuses_too(tmp_path, monkeypatch):
    """Every component from staging/ down is walked: a link planted deeper
    (staging/context_layer/policies) is refused just the same."""
    doc = make_doc(tmp_path)
    staging = tmp_path / "staging"
    outside = tmp_path / "outside"
    (outside / "policies").mkdir(parents=True)
    (staging / "context_layer").mkdir(parents=True)
    (staging / "context_layer" / "policies").symlink_to(outside / "policies")

    _, staged, errors, _ = run_ingest(tmp_path, doc, [response(page_entry())], monkeypatch)

    assert staged == []
    assert not list((outside / "policies").iterdir())
    assert any("symlink" in error for error in errors)


# --- (i) secret scan: LLM output is untrusted ------------------------------


def test_secret_token_in_body_rejects_page_naming_class_not_secret(tmp_path, monkeypatch):
    """A source document's credentials echoed by the LLM must never reach
    staging: the page is rejected naming the pattern CLASS, the secret value
    itself appears nowhere in the feedback or errors, and nothing is staged."""
    doc = make_doc(tmp_path)
    secret = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1"  # fake token, 24 chars
    poisoned = page_entry(body=f"# Rotation\n\nuse {secret} in prod\n")
    staging, staged, errors, calls = run_ingest(
        tmp_path,
        doc,
        [response(poisoned)],
        monkeypatch,  # replayed every round
    )

    assert len(calls) == 1 + MAX_RETRIES  # every round violates
    assert staged == [] and not (staging / "context_layer").exists()
    feedback = calls[1][-1]["content"]
    assert "api_token" in feedback  # pattern CLASS named
    assert secret not in feedback and secret not in str(errors)  # value never echoed


def test_secret_page_rejected_then_clean_retry_stages(tmp_path, monkeypatch):
    """The retry loop continues without the secret: a clean round stages."""
    doc = make_doc(tmp_path)
    secret = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1"
    staging, staged, errors, calls = run_ingest(
        tmp_path,
        doc,
        [response(page_entry(body=f"key {secret}")), response(page_entry())],
        monkeypatch,
    )

    assert len(calls) == 2  # round 1 rejected, round 2 recovered
    assert staged and front_of(staged[0])["status"] == "draft"
    assert not any(secret in page.read_text(encoding="utf-8") for page in staged)


@pytest.mark.parametrize(
    ("entry", "expected_class"),
    [
        (
            page_entry(body="# key\n\n-----BEGIN RSA PRIVATE KEY-----\nMIIEpA...\n"),
            "private_key",
        ),
        (page_entry(body="# aws\n\nid AKIAIOSFODNN7EXAMPLE\n"), "aws_access_key"),
        # frontmatter values are scanned too: title renders into the YAML block
        (page_entry(title="the settings password: hunter2"), "credential_assignment"),
        (
            page_entry(body="curl -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9'"),
            "bearer_token",
        ),
    ],
)
def test_secret_scan_covers_frontmatter_and_every_pattern_class(
    tmp_path, monkeypatch, entry, expected_class
):
    doc = make_doc(tmp_path)
    _, staged, errors, _ = run_ingest(tmp_path, doc, [response(entry)], monkeypatch)

    assert staged == []
    assert any(expected_class in error for error in errors)


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
    assert (
        main(
            [
                str(doc),
                "--db",
                "examples/retail-demo/data/demo.db",
                "--staging",
                str(tmp_path / "s"),
            ]
        )
        == 0
    )


# --- (j) opt-in evidence reconciliation (spec 2026-09-23-0004, issue #12 unit A) ---


APPROVED = "policies/churned-arr-not-expansion.md"  # context-layer-relative path
PROMOTED_AT = "2026-09-24T10:00:00+00:00"


def _served_snapshot(served: Path) -> dict[str, bytes]:
    """Every served file's bytes — reconcile must leave them byte-identical."""
    return {
        p.relative_to(served).as_posix(): p.read_bytes()
        for p in sorted(served.rglob("*"))
        if p.is_file()
    }


def test_reconcile_journey(tmp_path, monkeypatch):
    """One public-entry journey: human-edited served Policy preserved, exact-path
    replacement with source-linked diff, unchanged repeat, provenance-only update,
    path-drift warning, same-path source mismatch, multi-page preflight, occupied
    target, and ordinary ingestion unchanged (spec 2026-09-23-0004 AC1–AC3/AC5)."""
    monkeypatch.setenv("OPENAI_MODEL", MODEL)
    served = tmp_path / "served"
    doc = make_doc(tmp_path)

    # (1) ordinary ingest + human promotion establish the approved page
    staging1 = tmp_path / "staging-first"
    staged, errors = ingest([doc], staging_dir=staging1, complete=lambda _m: response(page_entry()))
    assert errors == [] and len(staged) == 1
    promote(staging1, served, by="human:alice", assume_yes=True, at=PROMOTED_AT)
    approved = served / "context_layer" / APPROVED
    assert approved.is_file()

    # (2) concrete human edit of the served Policy
    human_text = approved.read_text(encoding="utf-8").replace(
        "CHURNED rows record lost ARR.", "CHURNED rows record lost ARR. (annotated by the owner.)"
    )
    approved.write_text(human_text, encoding="utf-8")

    # (3) reconcile a revised document: changed rule text -> proposal at the EXACT
    # approved path; served tree byte-identical; diff and old/new digest visible
    doc.write_text("# Renewal notes v2\n\nCHURNED never counts toward expansion or net new ARR.\n")
    changed_entry = page_entry(
        body="# Churned ARR is not expansion\n\nCHURNED rows record lost ARR and never count "
        "toward net new either."
    )
    snapshot = _served_snapshot(served)
    staging2 = tmp_path / "staging-changed"
    no_conflict = _advisor_aware_complete(changed_entry, json.dumps({"possible_conflict": False}))
    staged, errors, comparisons = reconcile_ingest(
        [doc],
        served_root=served,
        staging_dir=staging2,
        complete=no_conflict,
    )
    assert errors == []
    (proposal,) = staged
    assert proposal == staging2 / "context_layer" / APPROVED  # exact approved path, no suffix
    assert _served_snapshot(served) == snapshot  # human edit byte-identical, nothing served
    (record,) = comparisons
    assert record.proposal == APPROVED
    assert record.match == "same-path" and record.change == "changed"
    assert record.old_source is not None
    assert record.old_source["digest"] != record.new_source["digest"]  # v1 vs v2 doc bytes
    assert record.old_source["resource"] == record.new_source["resource"] == str(doc.resolve())
    diff_lines = record.diff.splitlines()
    assert "-CHURNED rows record lost ARR. (annotated by the owner.)" in diff_lines
    assert "+CHURNED rows record lost ARR and never count toward net new either." in diff_lines
    assert record.advisory.status == "none"  # eligible, but this fake model suggests nothing
    front = front_of(proposal)
    assert front["status"] == "draft"  # still a proposal: promotion stays human
    assert front["sources"][0]["id"] == hashlib.sha256(doc.read_bytes()).hexdigest()[:12]

    # (4) promote the proposal, then re-reconcile identical input: unchanged, stages nothing
    promote(staging2, served, by="human:alice", assume_yes=True, at="2026-09-24T11:00:00+00:00")
    staging3 = tmp_path / "staging-unchanged"
    staged, errors, comparisons = reconcile_ingest(
        [doc],
        served_root=served,
        staging_dir=staging3,
        complete=lambda _m: response(changed_entry),
    )
    assert staged == [] and errors == []
    (record,) = comparisons
    assert record.change == "unchanged" and record.staged is None
    assert not (staging3 / "context_layer").exists()  # nothing at all was staged

    # (5) provenance-only: identical rule text, changed source bytes
    doc.write_text(doc.read_text(encoding="utf-8") + "\n(v2 re-export with new bytes)\n")
    staging4 = tmp_path / "staging-provenance"
    staged, errors, comparisons = reconcile_ingest(
        [doc],
        served_root=served,
        staging_dir=staging4,
        complete=lambda _m: response(changed_entry),  # same page content as served
    )
    assert errors == []
    (proposal,) = staged
    assert proposal == staging4 / "context_layer" / APPROVED  # corrected citation, exact path
    (record,) = comparisons
    assert record.change == "provenance_only"
    digest = hashlib.sha256(doc.read_bytes()).hexdigest()[:12]
    assert front_of(proposal)["sources"][0]["id"] == digest

    # (6) path drift: same source document, renamed proposal path -> duplicate
    # warning, staged as a NEW page (never silently retargeted)
    staging5 = tmp_path / "staging-drift"
    staged, errors, comparisons = reconcile_ingest(
        [doc],
        served_root=served,
        staging_dir=staging5,
        complete=lambda _m: response(page_entry(name="churned-arr-not-expansion-v2")),
    )
    assert errors == []
    (proposal,) = staged
    assert proposal == staging5 / "context_layer" / "policies" / "churned-arr-not-expansion-v2.md"
    (record,) = comparisons
    assert record.match == "new" and record.change == "new"
    assert record.warning is not None
    assert "possible duplicate" in record.warning
    assert "policies/churned-arr-not-expansion.md" in record.warning
    assert record.staged == proposal  # final path reported explicitly

    # (7) same-path source mismatch + multi-page preflight: NOTHING from that doc
    other = tmp_path / "other-playbook.md"
    other.write_text("# Another team's playbook\n\nTheir own rule.\n", encoding="utf-8")
    staging6 = tmp_path / "staging-mismatch"
    staged, errors, comparisons = reconcile_ingest(
        [other],
        served_root=served,
        staging_dir=staging6,
        complete=lambda _m: response(
            page_entry(
                name="seat-based-renewal-window",
                title="Seat-based renewal window",
                description="Seats renew in the booked month.",
                body="# Seat-based renewal window\n\nSeats renew in the booked month.",
            ),
            page_entry(),  # same path as the approved page, WRONG source document
        ),
    )
    assert staged == [] and comparisons == []
    assert any("identity conflict" in e and APPROVED in e for e in errors)
    assert not (staging6 / "context_layer").exists()  # the innocent page staged nothing either

    # (8) occupied replacement target: error, no -2 suffix, no overwrite
    staging7 = tmp_path / "staging-occupied"
    occupied = staging7 / "context_layer" / APPROVED
    occupied.parent.mkdir(parents=True)
    occupied.write_text("---\ntype: policy\n---\n\nearlier proposal\n", encoding="utf-8")
    staged, errors, comparisons = reconcile_ingest(
        [doc],
        served_root=served,
        staging_dir=staging7,
        complete=lambda _m: response(
            page_entry(body="# Churned ARR is not expansion\n\nRewritten again for v3.")
        ),
    )
    assert staged == [] and comparisons == []
    assert any("occupied" in e and APPROVED in e for e in errors)
    assert occupied.read_text(encoding="utf-8").startswith("---\ntype: policy")  # untouched

    # (9) ordinary mode keeps its collision-suffix behavior and 2-tuple shape
    staging8 = tmp_path / "staging-ordinary"
    existing = staging8 / "context_layer" / APPROVED
    existing.parent.mkdir(parents=True)
    existing.write_text("x", encoding="utf-8")
    staged, errors = ingest(
        [doc],
        staging_dir=staging8,
        complete=lambda _m: response(
            page_entry(body="# Churned ARR is not expansion\n\nRewritten again for v3.")
        ),
    )
    assert errors == []
    assert staged == [staging8 / "context_layer" / "policies" / "churned-arr-not-expansion-2.md"]


def test_reconcile_invalid_served_root_fails_before_model_or_writes(tmp_path, monkeypatch):
    """A served root without context_layer/ fails before any model call or write."""

    def boom(_messages):
        raise AssertionError("model must not be called")

    staging = tmp_path / "staging"
    with pytest.raises(ValueError, match="context_layer"):
        reconcile_ingest(
            [make_doc(tmp_path)],
            served_root=tmp_path / "nope",
            staging_dir=staging,
            complete=boom,
        )
    assert not staging.exists()  # nothing was staged


def test_cli_reconcile_reports_match_diff_and_sources(tmp_path, monkeypatch, capsys):
    """--reconcile --served prints the match, change class, old/new source digests
    and the bounded diff, staging the proposal at the exact approved path."""
    import ariadne.ingest as ingest_module

    monkeypatch.setenv("OPENAI_MODEL", MODEL)
    doc = make_doc(tmp_path)
    monkeypatch.setattr(ingest_module, "_default_complete", lambda _m: response(page_entry()))
    assert main([str(doc), "--staging", str(tmp_path / "s1")]) == 0
    promote(tmp_path / "s1", tmp_path / "served", by="human:alice", assume_yes=True, at=PROMOTED_AT)
    approved = tmp_path / "served" / "context_layer" / APPROVED
    approved.write_text(
        approved.read_text(encoding="utf-8").replace(
            "CHURNED rows record lost ARR.", "CHURNED rows record lost ARR. (owner note)"
        ),
        encoding="utf-8",
    )

    doc.write_text("# Renewal notes v2\n\nCHURNED never counts toward net new ARR.\n")
    monkeypatch.setattr(
        ingest_module,
        "_default_complete",
        lambda _m: response(page_entry(body="# Churned ARR is not expansion\n\nRewritten for v2.")),
    )
    code = main(
        [
            str(doc),
            "--reconcile",
            "--served",
            str(tmp_path / "served"),
            "--staging",
            str(tmp_path / "s2"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert f"reconcile: {APPROVED}" in out and "same-path" in out and "changed" in out
    assert "old source:" in out and "new source:" in out
    assert "-CHURNED rows record lost ARR. (owner note)" in out
    assert (tmp_path / "s2" / "context_layer" / APPROVED).is_file()


def test_cli_reconcile_requires_served_before_any_model_call(tmp_path, monkeypatch, capsys):
    """--reconcile without --served is a CLI error before any model call."""
    import ariadne.ingest as ingest_module

    def boom(_messages):
        raise AssertionError("model must not be called")

    monkeypatch.setattr(ingest_module, "_default_complete", boom)
    with pytest.raises(SystemExit):
        main([str(make_doc(tmp_path)), "--reconcile"])
    assert "--served" in capsys.readouterr().err


# --- (k) immediate-review fix pass (issue #12 unit A, authorized findings) ------


def _approved_state(tmp_path, entry, text=None):
    """Ingest one page entry and promote it: returns (served root, document)."""
    doc = make_doc(tmp_path, text=text)
    staging = tmp_path / "staging-seed"
    staged, errors = ingest([doc], staging_dir=staging, complete=lambda _m: response(entry))
    assert errors == [] and len(staged) == 1
    promote(staging, tmp_path / "served", by="human:alice", assume_yes=True, at=PROMOTED_AT)
    return tmp_path / "served", doc


def test_reconcile_rejects_staging_inside_the_served_root(tmp_path):
    """Finding 1: staging_dir overlapping the caller-selected served root would
    let a new page land directly in served state, bypassing promotion."""
    served, doc = _approved_state(tmp_path, page_entry())

    def boom(_messages):
        raise AssertionError("model must not be called")

    with pytest.raises(ValueError, match="served root"):
        reconcile_ingest([doc], served_root=served, staging_dir=served, complete=boom)
    with pytest.raises(ValueError, match="served root"):
        reconcile_ingest(
            [doc], served_root=served, staging_dir=served / "nested-staging", complete=boom
        )
    assert not (served / "nested-staging").exists()  # nothing was written


def test_reconcile_detects_changed_table_grain_as_changed(tmp_path):
    """Finding 2: a human edit to substantive per-type metadata (table grain)
    must stay a visible change, not classify as unchanged."""
    entry = page_entry(
        folder="tables",
        name="renewals",
        type="table",
        title="Renewals",
        description="One row per renewal event.",
        tags=["table", "renewals"],
        grain={
            "primary_key": ["account_id", "renewal_date"],
            "cardinality_enforcement": "STRICT_1_TO_1",
        },
        body="# Renewals\n\nOne row per renewal event.",
    )
    served, doc = _approved_state(tmp_path, entry)
    page = served / "context_layer" / "tables" / "renewals.md"
    page.write_text(
        page.read_text(encoding="utf-8").replace(
            "cardinality_enforcement: STRICT_1_TO_1", "cardinality_enforcement: ONE_TO_MANY"
        ),
        encoding="utf-8",
    )

    staging = tmp_path / "staging-grain"
    staged, errors, comparisons = reconcile_ingest(
        [doc], served_root=served, staging_dir=staging, complete=lambda _m: response(entry)
    )
    assert errors == []
    (record,) = comparisons
    assert record.change == "changed"  # grain is owner metadata, not bookkeeping
    assert "STRICT_1_TO_1" in record.diff
    (proposal,) = staged
    assert proposal == staging / "context_layer" / "tables" / "renewals.md"


def test_reconcile_uses_the_matching_approved_source_for_identity(tmp_path):
    """Finding 3: with several approved citations, old source/digest must follow
    the entry that actually matched, not the first entry."""
    served, doc = _approved_state(tmp_path, page_entry())
    page = served / "context_layer" / APPROVED
    page.write_text(
        page.read_text(encoding="utf-8").replace(
            "sources:\n",
            "sources:\n"
            "- id: '000000000000'\n"
            "  resource: /elsewhere/original-handbook.docx\n"
            "  title: original-handbook.docx\n",
            1,
        ),
        encoding="utf-8",
    )

    staging = tmp_path / "staging-two-sources"
    staged, errors, comparisons = reconcile_ingest(
        [doc], served_root=served, staging_dir=staging, complete=lambda _m: response(page_entry())
    )
    assert errors == []
    assert staged == []  # identical page and identical MATCHED digest: unchanged
    (record,) = comparisons
    assert record.change == "unchanged"
    assert record.old_source is not None
    assert record.old_source["resource"] == str(doc.resolve())
    assert record.old_source["digest"] == hashlib.sha256(doc.read_bytes()).hexdigest()[:12]


def test_reconcile_duplicate_scan_never_reads_symlinked_candidates(tmp_path):
    """Finding 4: duplicate discovery must not read through a symlink planted in
    the served tree (an out-of-layer read steered by the proposed path)."""
    served, doc = _approved_state(tmp_path, page_entry())
    outside = tmp_path / "outside" / "decoy.md"  # content lives OUTSIDE the served root
    outside.parent.mkdir(parents=True)
    outside.write_text(
        "---\ntype: policy\ntitle: Churned ARR is not expansion\n---\n\ndecoy\n",
        encoding="utf-8",
    )
    # sorts BEFORE the real page, so an unguarded scan would read it first
    (served / "context_layer" / "policies" / "aaa-decoy.md").symlink_to(outside)

    staging = tmp_path / "staging-scan"
    staged, errors, comparisons = reconcile_ingest(
        [doc],
        served_root=served,
        staging_dir=staging,
        complete=lambda _m: response(page_entry(name="churned-arr-not-expansion-v2")),
    )
    assert errors == []
    (proposal,) = staged  # the unmatched new page still stages
    assert proposal.name == "churned-arr-not-expansion-v2.md"
    (record,) = comparisons
    assert record.warning is not None
    assert "possible duplicate" in record.warning
    assert "aaa-decoy.md" not in record.warning  # the symlinked decoy was never read
    assert "policies/churned-arr-not-expansion.md" in record.warning  # the real suspect


def test_reconcile_duplicate_proposed_path_detected_even_when_first_is_unchanged(tmp_path):
    """Finding 5: the same proposed path emitted twice must fail preflight even
    when the first occurrence classifies unchanged (it never enters the plan)."""
    served, doc = _approved_state(tmp_path, page_entry())
    changed = page_entry(body="# Churned ARR is not expansion\n\nRewritten body.")

    staging = tmp_path / "staging-dup"
    staged, errors, comparisons = reconcile_ingest(
        [doc],
        served_root=served,
        staging_dir=staging,
        complete=lambda _m: response(page_entry(), changed),  # same path: unchanged, changed
    )
    assert staged == [] and comparisons == []
    assert any("duplicate proposal path" in e and APPROVED in e for e in errors)
    assert not (staging / "context_layer").exists()  # preflight failed: nothing staged


# --- (l) opt-in conflict advisory (spec 2026-09-23-0004 AC4, issue #12 unit B) ---


def _approved_policy_with_human_edit(tmp_path, *, annotation="(owner annotation)"):
    """Approved policy + human-edited served body + a revised document and its
    changed rendering; returns (served, doc, changed_entry)."""
    served, doc = _approved_state(tmp_path, page_entry())
    approved = served / "context_layer" / APPROVED
    approved.write_text(
        approved.read_text(encoding="utf-8").replace(
            "CHURNED rows record lost ARR.", f"CHURNED rows record lost ARR. {annotation}"
        ),
        encoding="utf-8",
    )
    doc.write_text(
        "# Renewal notes v2\n\nCHURNED rows never count toward expansion nor net new ARR.\n"
    )
    changed_entry = page_entry(
        body="# Churned ARR is not expansion\n\nCHURNED rows record lost ARR and never "
        "count toward net new either."
    )
    return served, doc, changed_entry


def test_reconcile_advisory_supported_quotes_for_changed_policy(tmp_path, monkeypatch):
    """Unit B eligibility + quote verification: ONLY a same-path matched approved
    POLICY with changed body gets the extra call; the provider receives the
    converted document and the approved Policy title/body/source identity —
    never verified identities — and each quote is checked verbatim."""
    monkeypatch.setenv("OPENAI_MODEL", MODEL)
    served, doc, changed_entry = _approved_policy_with_human_edit(tmp_path)
    calls: list[list[dict]] = []

    def complete(messages):
        calls.append(messages)
        if len(calls) == 1:
            return response(changed_entry)  # distillation
        return json.dumps(
            {
                "possible_conflict": True,
                "note": "the revision drops the net-new exclusion",
                "quotes": [
                    "CHURNED rows record lost ARR. (owner annotation)",  # verbatim: approved
                    "CHURNED rows never count toward expansion nor net new ARR.",  # verbatim: doc
                    "INVENTED passage present in neither text",  # must come back unverified
                ],
            }
        )

    staging = tmp_path / "staging-advisory"
    staged, errors, comparisons = reconcile_ingest(
        [doc], served_root=served, staging_dir=staging, complete=complete
    )
    assert errors == []
    (proposal,) = staged  # deterministic staging is independent of the advisory
    assert proposal == staging / "context_layer" / APPROVED
    (record,) = comparisons
    assert record.change == "changed"

    advisory = record.advisory
    assert advisory.status == "supported"
    assert advisory.note == "the revision drops the net-new exclusion"
    assert advisory.quotes is not None
    verified = {q["text"] for q in advisory.quotes if q["verified"]}
    unverified = [q["text"] for q in advisory.quotes if not q["verified"]]
    assert verified == {
        "CHURNED rows record lost ARR. (owner annotation)",
        "CHURNED rows never count toward expansion nor net new ARR.",
    }
    assert unverified == ["INVENTED passage present in neither text"]

    # egress contract: exactly one extra call, advisory-shaped, minimal content
    assert len(calls) == 2
    payload = calls[1][-1]["content"]
    assert "CHURNED rows never count toward expansion nor net new ARR." in payload  # converted doc
    assert "CHURNED rows record lost ARR. (owner annotation)" in payload  # approved body
    assert "Churned ARR is not expansion" in payload  # approved title
    assert str(doc.resolve()) in payload  # source identity
    assert "human:alice" not in payload  # verified identities never leave the layer
    assert "verified" not in calls[1][0]["content"]  # system prompt carries none either


def test_reconcile_advisory_refuses_credential_pattern_before_any_egress(tmp_path):
    """An approved Policy that appears to contain a credential is NEVER sent:
    no extra model call at all, the class (not the secret) is reported, and the
    deterministic diff + staging stand."""
    served, doc, changed_entry = _approved_policy_with_human_edit(
        tmp_path, annotation="(api token: sk-a1B2c3D4e5F6g7H8i9J0k1 in a note)"
    )
    secret = "sk-a1B2c3D4e5F6g7H8i9J0k1"
    calls: list[list[dict]] = []

    def complete(messages):
        calls.append(messages)
        return response(changed_entry)

    staging = tmp_path / "staging-refused"
    staged, errors, comparisons = reconcile_ingest(
        [doc], served_root=served, staging_dir=staging, complete=complete
    )
    assert errors == []
    (proposal,) = staged  # staging is unaffected by the refusal
    assert proposal == staging / "context_layer" / APPROVED
    (record,) = comparisons
    assert record.change == "changed" and record.diff  # deterministic diff stands
    advisory = record.advisory
    assert advisory.status == "unavailable"
    assert "api_token" in advisory.reason  # pattern CLASS named
    assert secret not in advisory.reason and secret not in str(advisory)  # secret never echoed
    assert len(calls) == 1  # distillation only: the approved text never left
    assert not any(secret in str(c) for c in calls)


def test_reconcile_advisory_invented_quotes_are_unverified(tmp_path):
    """A suggestion whose quotes appear in neither text is unverified, never
    evidence — while the deterministic diff and staging persist."""
    served, doc, changed_entry = _approved_policy_with_human_edit(tmp_path)

    def complete(messages):
        if any(
            m["role"] == "system" and "reconciliation advisor" in m["content"] for m in messages
        ):
            return json.dumps(
                {
                    "possible_conflict": True,
                    "note": "fabricated concern",
                    "quotes": ["made up passage one", "made up passage two"],
                }
            )
        return response(changed_entry)

    staging = tmp_path / "staging-invented"
    staged, errors, comparisons = reconcile_ingest(
        [doc], served_root=served, staging_dir=staging, complete=complete
    )
    assert errors == []
    assert len(staged) == 1  # safe staging persists
    (record,) = comparisons
    advisory = record.advisory
    assert advisory.status == "unverified"
    assert advisory.quotes is not None and advisory.quotes
    assert all(not quote["verified"] for quote in advisory.quotes)


def test_reconcile_advisory_provider_failure_is_unavailable_but_stages(tmp_path):
    """A failing advisory call leaves the deterministic comparison visible,
    marks the advisory unavailable, and does not prevent safe staging."""
    served, doc, changed_entry = _approved_policy_with_human_edit(tmp_path)

    def complete(messages):
        if any(
            m["role"] == "system" and "reconciliation advisor" in m["content"] for m in messages
        ):
            raise RuntimeError("provider exploded")
        return response(changed_entry)

    staging = tmp_path / "staging-provider"
    staged, errors, comparisons = reconcile_ingest(
        [doc], served_root=served, staging_dir=staging, complete=complete
    )
    assert errors == []
    (proposal,) = staged  # staging happened despite the failure
    assert proposal == staging / "context_layer" / APPROVED
    (record,) = comparisons
    assert record.change == "changed" and "-CHURNED" in record.diff  # diff still visible
    assert record.advisory.status == "unavailable"
    assert "RuntimeError" in record.advisory.reason


def test_reconcile_advisory_no_suggestion_is_not_proof_of_consistency(tmp_path):
    """An absent suggestion is never reported as consistency."""
    served, doc, changed_entry = _approved_policy_with_human_edit(tmp_path)

    def complete(messages):
        if any(
            m["role"] == "system" and "reconciliation advisor" in m["content"] for m in messages
        ):
            return json.dumps({"possible_conflict": False})
        return response(changed_entry)

    staging = tmp_path / "staging-none"
    _, errors, comparisons = reconcile_ingest(
        [doc], served_root=served, staging_dir=staging, complete=complete
    )
    assert errors == []
    (record,) = comparisons
    assert record.advisory.status == "none"
    assert "not proof of consistency" in record.advisory.reason


def test_reconcile_advisory_skips_ineligible_pages(tmp_path):
    """No advisory call for unchanged, provenance-only, new, non-Policy or
    body-identical (title-only) changes: exactly one model call — distillation."""
    table_entry = page_entry(
        folder="tables",
        name="renewals",
        type="table",
        title="Renewals",
        description="One row per renewal event.",
        tags=["table", "renewals"],
        grain={"primary_key": ["account_id"], "cardinality_enforcement": "STRICT_1_TO_1"},
        body="# Renewals\n\nOne row per renewal event.",
    )

    def scenario(base: Path, entry, doc_mutate, served_edit) -> Reconciliation:
        base.mkdir(parents=True)
        served, doc = _approved_state(base, entry)
        served_edit(served / "context_layer" / entry["folder"] / f"{entry['name']}.md")
        doc_mutate(doc)
        calls: list[list[dict]] = []

        def complete(messages):
            calls.append(messages)
            return response(entry)

        _, errors, comparisons = reconcile_ingest(
            [doc], served_root=served, staging_dir=base / "staging", complete=complete
        )
        assert errors == [] and len(calls) == 1, errors  # distillation ONLY
        (record,) = comparisons
        return record

    def human_edit_body(path: Path) -> None:
        path.write_text(
            path.read_text(encoding="utf-8").replace("One row per renewal event.", "Human edit."),
            encoding="utf-8",
        )

    def human_edit_title(path: Path) -> None:
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "title: Churned ARR is not expansion", "title: Retitled by the owner"
            ),
            encoding="utf-8",
        )

    # unchanged: same document bytes, same rendered content, served untouched
    record = scenario(tmp_path / "c1", page_entry(), lambda doc: None, lambda path: None)
    assert record.change == "unchanged" and record.advisory.status == "not_applicable"
    # provenance-only: new document bytes, identical rendered content, served untouched
    record = scenario(
        tmp_path / "c2",
        page_entry(),
        lambda doc: doc.write_text(doc.read_text(encoding="utf-8") + "\n(re-export)\n"),
        lambda path: None,
    )
    assert record.change == "provenance_only" and record.advisory.status == "not_applicable"
    # new unmatched page (renamed path): staged as new, never advised
    renamed = page_entry(name="churned-arr-not-expansion-v2")
    base = tmp_path / "c3"
    base.mkdir(parents=True)
    served, doc = _approved_state(base, page_entry())
    calls = []

    def complete(messages):
        calls.append(messages)
        return response(renamed)

    _, errors, comparisons = reconcile_ingest(
        [doc], served_root=served, staging_dir=base / "staging", complete=complete
    )
    assert errors == [] and len(calls) == 1
    (record,) = comparisons
    assert record.change == "new" and record.advisory.status == "not_applicable"
    # non-Policy: changed approved table body
    record = scenario(tmp_path / "c4", table_entry, lambda doc: None, human_edit_body)
    assert record.change == "changed" and record.advisory.status == "not_applicable"
    # Policy with title-only change: body identical
    record = scenario(tmp_path / "c5", page_entry(), lambda doc: None, human_edit_title)
    assert record.change == "changed" and record.advisory.status == "not_applicable"


def test_reconcile_discloses_no_approved_policy_outside_eligibility(tmp_path):
    """Source mismatch and a symlinked approved path never send approved text:
    the only model call is the document distillation."""
    served, doc = _approved_state(tmp_path, page_entry())

    # (a) same-path source mismatch: preflight error, nothing staged
    other = tmp_path / "other-playbook.md"
    other.write_text("# Another playbook\n\nTheir rule.\n", encoding="utf-8")
    calls: list[list[dict]] = []

    def complete(messages):
        calls.append(messages)
        return response(page_entry())

    staging = tmp_path / "staging-mismatch-b"
    staged, errors, _ = reconcile_ingest(
        [other], served_root=served, staging_dir=staging, complete=complete
    )
    assert staged == [] and any("identity conflict" in e for e in errors)
    assert len(calls) == 1  # distillation only
    approved_body = "CHURNED rows record lost ARR."
    assert not any(approved_body in str(c) for c in calls)  # no approved text disclosed

    # (b) symlinked approved component: refused before any approved read
    base = tmp_path / "case-b"
    base.mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    served2, doc2 = _approved_state(base, page_entry())
    (served2 / "context_layer" / "policies").rename(outside / "policies")
    (served2 / "context_layer" / "policies").symlink_to(outside / "policies")
    calls2: list[list[dict]] = []

    def complete2(messages):
        calls2.append(messages)
        return response(page_entry())

    staging2 = tmp_path / "staging-symlink-b"
    staged2, errors2, _ = reconcile_ingest(
        [doc2], served_root=served2, staging_dir=staging2, complete=complete2
    )
    assert staged2 == [] and any("symlink" in e for e in errors2)
    assert len(calls2) == 1
    assert not any(approved_body in str(c) for c in calls2)


# --- (m) unit-B fix pass (parent-authorized P1/P2/P3 findings) -----------------


def _advisor_aware_complete(changed_entry, advisory_answer):
    """complete() that answers the distillation with the changed entry and the
    advisory call with ``advisory_answer`` (a JSON string)."""

    def complete(messages):
        if any(
            m["role"] == "system" and "reconciliation advisor" in m["content"] for m in messages
        ):
            return advisory_answer
        return response(changed_entry)

    return complete


def test_reconcile_advisory_uses_the_first_converted_text_when_doc_changes_mid_run(tmp_path):
    """P1: quote verification must use the SAME converted text the distillation
    saw — rewriting or deleting the document during the first model call can
    neither stale the evidence nor crash the finished comparison."""
    # case 1: the document is REWRITTEN during the distillation call; a quote
    # present only in the FIRST text must still verify.
    base = tmp_path / "c1"
    base.mkdir(parents=True)
    served, doc, changed_entry = _approved_policy_with_human_edit(base)

    def complete(messages):
        if any(
            m["role"] == "system" and "reconciliation advisor" in m["content"] for m in messages
        ):
            return json.dumps(
                {
                    "possible_conflict": True,
                    "note": "net-new exclusion dropped",
                    "quotes": ["never count toward expansion nor net new ARR."],
                }
            )
        doc.write_text("# totally different\n\nreplacement content\n", encoding="utf-8")
        return response(changed_entry)

    staging = base / "staging"
    staged, errors, comparisons = reconcile_ingest(
        [doc], served_root=served, staging_dir=staging, complete=complete
    )
    assert errors == []
    (proposal,) = staged
    assert proposal == staging / "context_layer" / APPROVED
    (record,) = comparisons
    assert record.change == "changed" and record.diff  # deterministic result stands
    assert record.advisory.status == "supported"  # verified against the FIRST text
    assert record.advisory.quotes and record.advisory.quotes[0]["verified"]

    # case 2: the document is DELETED during the distillation call; the finished
    # comparison, staging and a valid absence answer survive without a crash.
    base2 = tmp_path / "c2"
    base2.mkdir(parents=True)
    served2, doc2, changed_entry2 = _approved_policy_with_human_edit(base2)

    def complete2(messages):
        if any(
            m["role"] == "system" and "reconciliation advisor" in m["content"] for m in messages
        ):
            return json.dumps({"possible_conflict": False})
        doc2.unlink()  # the document vanishes mid-run
        return response(changed_entry2)

    staging2 = base2 / "staging"
    staged2, errors2, comparisons2 = reconcile_ingest(
        [doc2], served_root=served2, staging_dir=staging2, complete=complete2
    )
    assert errors2 == []
    (proposal2,) = staged2  # staging already happened before the advisory
    assert proposal2.is_file()
    (record2,) = comparisons2
    assert record2.change == "changed" and record2.diff
    assert record2.advisory.status == "none"


def test_reconcile_advisory_malformed_conflict_flag_is_unavailable(tmp_path):
    """P2: possible_conflict must be an explicit boolean — a missing or invalid
    flag is an unusable answer (unavailable), never an absence claim."""
    served, doc, changed_entry = _approved_policy_with_human_edit(tmp_path)
    payloads = [
        json.dumps({"note": "flag forgotten"}),
        json.dumps({"possible_conflict": "maybe"}),
        json.dumps({"possible_conflict": None}),
    ]
    for i, payload in enumerate(payloads):
        _, errors, comparisons = reconcile_ingest(
            [doc],
            served_root=served,
            staging_dir=tmp_path / f"staging-bad-{i}",
            complete=_advisor_aware_complete(changed_entry, payload),
        )
        assert errors == []
        (record,) = comparisons
        assert record.advisory.status == "unavailable", payload
        assert "possible_conflict" in record.advisory.reason


def test_reconcile_credential_refusal_redacts_secret_from_diff_and_cli_output(
    tmp_path, monkeypatch, capsys
):
    """P3: when the approved Policy matches a credential pattern, the returned
    AND printed diff must not echo the suspected secret — the diff stays useful
    and the staged proposal persists."""
    secret = "sk-a1B2c3D4e5F6g7H8i9J0k1"
    served, doc, changed_entry = _approved_policy_with_human_edit(
        tmp_path, annotation=f"(note: {secret} embedded)"
    )

    staging = tmp_path / "staging-redact"
    staged, errors, comparisons = reconcile_ingest(
        [doc],
        served_root=served,
        staging_dir=staging,
        complete=lambda _m: response(changed_entry),
    )
    assert errors == []
    (proposal,) = staged
    assert proposal.is_file()  # staging unaffected
    (record,) = comparisons
    assert record.change == "changed"
    assert record.advisory.status == "unavailable" and "api_token" in record.advisory.reason
    assert record.diff  # the bounded diff survives...
    assert secret not in record.diff  # ...without the token...
    assert "[redacted api_token]" in record.diff  # ...class named in its place
    assert secret not in str(record)

    # CLI review output: the same redaction on stdout
    import ariadne.ingest as ingest_module

    monkeypatch.setenv("OPENAI_MODEL", MODEL)
    base = tmp_path / "cli"
    base.mkdir(parents=True)
    served2, doc2, changed_entry2 = _approved_policy_with_human_edit(
        base, annotation=f"(note: {secret} embedded)"
    )
    monkeypatch.setattr(ingest_module, "_default_complete", lambda _m: response(changed_entry2))
    code = main(
        [
            str(doc2),
            "--reconcile",
            "--served",
            str(served2),
            "--staging",
            str(base / "s2"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert secret not in out
    assert "[redacted api_token]" in out
    assert (base / "s2" / "context_layer" / APPROVED).is_file()


# --- (n) owner-authorized exception: entire PEM block redacted from the diff ----


def test_reconcile_credential_refusal_redacts_entire_pem_block_from_diff_and_cli(
    tmp_path, monkeypatch, capsys
):
    """A recognized multiline PEM private key in the approved body must vanish
    WHOLE from the returned and printed diff — BEGIN header, payload and END
    marker — while the refusal, staging and surrounding diff stay intact."""
    pem_payload = "MIIEowIBAAKCAQEA7SYNTHETICnotAREALkeyPAYLOAD0123456789=="
    pem = f"-----BEGIN RSA PRIVATE KEY-----\n{pem_payload}\n-----END RSA PRIVATE KEY-----"
    served, doc, changed_entry = _approved_policy_with_human_edit(tmp_path, annotation=f"({pem})")
    calls: list[list[dict]] = []

    def complete(messages):
        calls.append(messages)
        return response(changed_entry)

    staging = tmp_path / "staging-pem"
    staged, errors, comparisons = reconcile_ingest(
        [doc], served_root=served, staging_dir=staging, complete=complete
    )
    assert errors == []
    (proposal,) = staged  # the refusal never blocks safe staging
    assert proposal.is_file() and "MIIEow" not in proposal.read_text(encoding="utf-8")
    (record,) = comparisons
    assert record.change == "changed"
    assert record.advisory.status == "unavailable" and "private_key" in record.advisory.reason
    assert len(calls) == 1  # refusal preceded any egress
    assert record.diff  # the bounded diff survives...
    assert pem_payload not in record.diff  # ...without the key payload...
    assert "BEGIN RSA PRIVATE KEY" not in record.diff  # ...or the header...
    assert "END RSA PRIVATE KEY" not in record.diff  # ...or the END marker
    assert "[redacted private_key]" in record.diff  # one marker names the class
    assert "CHURNED rows record lost ARR" in record.diff  # surrounding text kept useful
    # the served page and staged proposal are never altered by redaction
    assert pem_payload in (served / "context_layer" / APPROVED).read_text(encoding="utf-8")

    # CLI review output: same whole-block redaction on stdout
    import ariadne.ingest as ingest_module

    monkeypatch.setenv("OPENAI_MODEL", MODEL)
    base = tmp_path / "cli"
    base.mkdir(parents=True)
    served2, doc2, changed_entry2 = _approved_policy_with_human_edit(base, annotation=f"({pem})")
    monkeypatch.setattr(ingest_module, "_default_complete", lambda _m: response(changed_entry2))
    code = main(
        [
            str(doc2),
            "--reconcile",
            "--served",
            str(served2),
            "--staging",
            str(base / "s2"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert pem_payload not in out and "PRIVATE KEY" not in out
    assert "[redacted private_key]" in out
    assert (base / "s2" / "context_layer" / APPROVED).is_file()


# --- (o) candidate-review fix: description-token refusal + all-diff redaction ---


def _with_description_token(served: Path, token_line: str) -> None:
    """Human-edit the approved Policy's frontmatter description to carry a
    credential-looking assignment (metadata, not body)."""
    page = served / "context_layer" / APPROVED
    page.write_text(
        page.read_text(encoding="utf-8").replace(
            "description: CHURNED renewal rows are excluded from expansion totals.",
            f"description: {token_line}",
        ),
        encoding="utf-8",
    )


def test_reconcile_credential_in_approved_description_refuses_and_redacts(
    tmp_path, monkeypatch, capsys
):
    """Candidate-review finding: a credential token in the approved Policy's
    frontmatter DESCRIPTION must (a) trigger the refusal with NO extra model
    call and an advisory naming only the credential class, (b) never echo in
    the returned diff or CLI output while the diff stays useful, and (c) leave
    staging exact and the served page untouched. Metadata-only changes get the
    same redaction."""
    token = "hunter2-rotation"
    served, doc, changed_entry = _approved_policy_with_human_edit(tmp_path)
    _with_description_token(served, f"ops note (password = {token}) for renewals.")
    snapshot = _served_snapshot(served)
    calls: list[list[dict]] = []

    def complete(messages):
        calls.append(messages)
        return response(changed_entry)

    staging = tmp_path / "staging-desc-token"
    staged, errors, comparisons = reconcile_ingest(
        [doc], served_root=served, staging_dir=staging, complete=complete
    )
    assert errors == []
    (proposal,) = staged  # (c) exact approved path, staged
    assert proposal == staging / "context_layer" / APPROVED
    assert _served_snapshot(served) == snapshot  # (c) served byte-identical
    assert token in (served / "context_layer" / APPROVED).read_text(encoding="utf-8")
    (record,) = comparisons
    assert record.change == "changed"
    assert record.advisory.status == "unavailable"  # (a) class-only refusal
    assert "credential_assignment" in record.advisory.reason
    assert token not in record.advisory.reason
    assert len(calls) == 1  # (a) distillation only: description never egressed
    assert record.diff  # (b) useful diff survives...
    assert token not in record.diff  # ...without the token...
    assert "[redacted credential_assignment]" in record.diff
    assert "never count toward net new either." in record.diff  # change still visible

    # (b) CLI review output: same redaction on stdout
    import ariadne.ingest as ingest_module

    monkeypatch.setenv("OPENAI_MODEL", MODEL)
    base = tmp_path / "cli"
    base.mkdir(parents=True)
    served2, doc2, changed_entry2 = _approved_policy_with_human_edit(base)
    _with_description_token(served2, f"ops note (password = {token}) for renewals.")
    monkeypatch.setattr(ingest_module, "_default_complete", lambda _m: response(changed_entry2))
    code = main(
        [
            str(doc2),
            "--reconcile",
            "--served",
            str(served2),
            "--staging",
            str(base / "s2"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert token not in out
    assert "[redacted credential_assignment]" in out
    assert (base / "s2" / "context_layer" / APPROVED).is_file()

    # metadata-only change (body identical): no advisory call, same redaction
    base3 = tmp_path / "c3"
    base3.mkdir(parents=True)
    served3, doc3 = _approved_state(base3, page_entry())
    _with_description_token(served3, f"ops note (password = {token}) for renewals.")
    calls3: list[list[dict]] = []

    def complete3(messages):
        calls3.append(messages)
        return response(page_entry())  # identical rendering: only metadata differs

    staging3 = base3 / "staging"
    staged3, errors3, comparisons3 = reconcile_ingest(
        [doc3], served_root=served3, staging_dir=staging3, complete=complete3
    )
    assert errors3 == [] and len(staged3) == 1  # changed metadata still stages
    (record3,) = comparisons3
    assert record3.change == "changed" and record3.advisory.status == "not_applicable"
    assert len(calls3) == 1  # body unchanged: not advisory-eligible, no egress
    assert token not in record3.diff
    assert "[redacted credential_assignment]" in record3.diff
