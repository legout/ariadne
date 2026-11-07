# Sample corpus: one synthetic document per format

A small, fully synthetic corpus — one file per supported input format — for
trying the documented Lumio Workspace and document journeys with consistent,
independently checkable content. Every expected value in this README was
**hand-set** from the fixture design; none was copied from importer or
converter output. All names, companies, and numbers are fictional.

The [shared-workspace journey](../shared-workspace-journey/README.md) (W6)
carries its own embedded fixtures with pinned hashes; this corpus is the
standalone counterpart for ad-hoc walks of the same pipelines.

## Files and their journeys

| File | Format | Journey / pipeline | Read by |
| --- | --- | --- | --- |
| `operations-notes.md` | Markdown | Document contribution: local Knowledge Base authoring ([quickstart](../../docs/quickstart.md)), document-first candidates ([how-to](../../docs/howto-document-first.md)), `/workspace-upload` document pipeline ([how-to](../../docs/howto-shared-workspace.md)) | native Markdown |
| `supplier-brief.pdf` | PDF (minimal, stdlib-built) | `/workspace-upload` binary document leg | LiteParse |
| `installation-note.docx` | DOCX (minimal OOXML, stdlib-built) | `/workspace-upload` binary document leg | AnyDoc / markitdown |
| `orders.csv` | CSV | Structured upload via `prepare_data_source` ([data how-to](../../../ariadne/docs/how-to/shared-workspace-data.md)) | DuckDB `read_csv_auto` |
| `orders.json` | JSON array | Structured upload via `prepare_data_source` | DuckDB `read_json_auto` |
| `orders.parquet` | Parquet (generated from `orders.csv` via DuckDB) | Structured upload via `prepare_data_source` | DuckDB `read_parquet` |
| `catalog.xlsx` | XLSX with formulas | XLSX import with explicit sheet selection ([data how-to](../../../ariadne/docs/how-to/shared-workspace-data.md), [data sources](../../../ariadne/docs/reference/data-sources.md)) | `ariadne-data[spreadsheets]` importer |

## Expected contents (hand-set oracles)

### `operations-notes.md`

Three sections (Ownership, Meeting notes, Escalation). Sentinels: the Beacon
lighting system is operated by *Harbor Point Facilities*; a storm-alert
inspection happens *within 30 minutes*; log retention of *90 days* is a
**proposal, not an adopted policy**.

### `orders.csv` / `orders.json` / `orders.parquet` (same dataset)

12 orders (Q1 2026, three regions, four customers: Nordwind GmbH, Suedlicht
AG, Ostwind UG, Hafenbau Sued):

- row count **12**; distinct customers **4**
- total `quantity` **121**; total `net_amount_eur` **10550.00**
- product line `panels`: **6 orders**, quantity **100**, net **5000.00**
  (batteries 15/3750.00, inverters 6/1800.00)
- regions north/south/east: **4 orders each**
- January 2026: **4 orders**, net **3100.00**

Type note (expected, not a defect): with DuckDB's auto-detection, CSV and
Parquet arrive typed (`order_date` as DATE, `net_amount_eur` as
DECIMAL(10,2) in Parquet), while `read_json_auto` keeps dates as strings;
compare values, not storage types, across the three formats.

### `catalog.xlsx`

Sheet `pricing` — price list, header row plus **4 data rows**
(P-100 panel, P-200 rail, I-300 inverter, B-400 battery). Column
`list_price_eur` holds formulas `=C{r}*(1+D{r}/100)` with **stored cached
values** (hand-computed: 32·1.25=**40**, 8·1.5=**12**, 210·1.4=**294**,
160·1.3=**208**). Importing `sheets=["pricing"]` must report four formula
cells with `cache_freshness: "unknown"` and store the cached list prices
40/12/294/208 — no recalculation ever happens.

Sheet `draft_totals` — the **deliberate variant**: cell D2 holds `=B2+C2`
with **no stored cached value** (exactly what openpyxl writes for formulas).
Selecting this sheet must **refuse** with `missing_formula_cache`; fix or
exclude the cell/sheet through a new reviewed selection instead.

### `supplier-brief.pdf`

One page, built as a minimal valid PDF by hand (Helvetica, no compression).
Text: "Harbor Point Supplier Brief", deliveries arrive at **dock 4** on
weekdays, delivery notes are signed **within 30 minutes**.

### `installation-note.docx`

One Heading 1 ("Beacon Installation Note") plus two paragraphs: mount the
mast at least **12 meters** from the fuel store; Kester Logistics delivers
spare bulbs with the next panel shipment.

## Regeneration

The three text files (`operations-notes.md`, `orders.csv`, `orders.json`)
are committed inputs and are never regenerated. The four binary files are
regenerated deterministically by:

```sh
# from the repository root, with the root .venv providing duckdb and the
# ariadne-data[spreadsheets] extra (openpyxl):
.venv/bin/python products/lumio/examples/sample-corpus/tools/generate_binary_sources.py
```

`orders.parquet` is derived from `orders.csv` (columns explicitly typed in
the script); `catalog.xlsx` is written with openpyxl, and a stdlib pass
injects the stored cached values into the `pricing` formula cells (openpyxl
alone cannot write caches — see the `draft_totals` sheet for the cache-less
result). PDF and DOCX are assembled with the standard library only. No new
dependencies are introduced anywhere.
