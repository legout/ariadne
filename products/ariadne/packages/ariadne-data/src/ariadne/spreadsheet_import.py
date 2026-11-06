"""Import explicitly selected XLSX sheets as immutable stored-value DuckDB data."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import re
import shutil
import tempfile
import time
import zipfile
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from datetime import time as datetime_time
from itertools import zip_longest
from pathlib import Path
from typing import Any

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

MAX_WORKBOOK_BYTES = 25 * 1024 * 1024
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_SELECTED_NONEMPTY_CELLS = 200_000
CONVERSION_DEADLINE_SECONDS = 20.0
_ERROR_VALUES = frozenset(
    {"#NULL!", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#N/A", "#GETTING_DATA"}
)


class SpreadsheetImportError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_workbook") -> None:
        super().__init__(message)
        self.code = code


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise SpreadsheetImportError(
            "XLSX conversion exceeded the 20-second worker deadline; no artifact was activated",
            code="conversion_deadline",
        )


def _sha256(path: Path, deadline: float | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            if deadline is not None:
                _check_deadline(deadline)
            digest.update(chunk)
    return digest.hexdigest()


def _selected_sheets(sheets: Sequence[str]) -> list[str]:
    if isinstance(sheets, (str, bytes)) or not isinstance(sheets, Sequence):
        raise SpreadsheetImportError(
            "sheets must be an explicit nonempty sequence of worksheet names",
            code="invalid_sheet_selection",
        )
    selected = list(sheets)
    if (
        not selected
        or any(not isinstance(name, str) or not name.strip() for name in selected)
        or len(set(selected)) != len(selected)
    ):
        raise SpreadsheetImportError(
            "sheets must contain unique, nonempty worksheet names",
            code="invalid_sheet_selection",
        )
    return sorted(selected)


def _preflight_archive(source: Path, deadline: float) -> None:
    try:
        with zipfile.ZipFile(source) as archive:
            expanded = 0
            names = set()
            for info in archive.infolist():
                _check_deadline(deadline)
                if info.flag_bits & 0x1:
                    raise SpreadsheetImportError(
                        "encrypted XLSX archives are unsupported",
                        code="unsupported_workbook",
                    )
                expanded += info.file_size
                if expanded > MAX_EXPANDED_BYTES:
                    raise SpreadsheetImportError(
                        "XLSX expanded archive exceeds the 64 MiB limit",
                        code="expanded_archive_too_large",
                    )
                names.add(info.filename)
            if any(name.startswith("xl/externalLinks/") for name in names):
                raise SpreadsheetImportError(
                    "workbook external links are refused; no external data was fetched",
                    code="external_links",
                )
            if "xl/workbook.xml" not in names:
                raise SpreadsheetImportError(
                    "the selected file is not an XLSX workbook",
                    code="invalid_workbook",
                )
    except zipfile.BadZipFile as exc:
        raise SpreadsheetImportError(
            "the selected file is not a valid XLSX ZIP archive", code="invalid_workbook"
        ) from exc


def _normalize(value: object, fallback: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text).strip("_")
    if not text:
        text = fallback
    if not text[0].isalpha():
        text = f"{fallback}_{text}"
    return text[:64]


def _unique_name(value: object, fallback: str, used: set[str]) -> str:
    base = _normalize(value, fallback)
    name = base
    suffix = 2
    while name in used:
        ending = f"__{suffix}"
        name = f"{base[: 64 - len(ending)]}{ending}"
        suffix += 1
    used.add(name)
    return name


def _json_value(value: object) -> object:
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, (datetime, date, datetime_time)):
        return value.isoformat()
    return value


def _duckdb_type(values: list[object], where: str) -> str:
    present = [value for value in values if value is not None]
    if not present:
        return "VARCHAR"
    if all(isinstance(value, bool) for value in present):
        return "BOOLEAN"
    if all(isinstance(value, int) and not isinstance(value, bool) for value in present):
        return "BIGINT"
    if all(
        isinstance(value, (int, float)) and not isinstance(value, bool) for value in present
    ):
        return "DOUBLE"
    if all(isinstance(value, datetime) for value in present):
        return "TIMESTAMP"
    if all(isinstance(value, date) and not isinstance(value, datetime) for value in present):
        return "DATE"
    if all(isinstance(value, datetime_time) for value in present):
        return "TIME"
    if all(isinstance(value, timedelta) for value in present):
        return "INTERVAL"
    if all(isinstance(value, str) for value in present):
        return "VARCHAR"
    raise SpreadsheetImportError(
        f"{where} mixes incompatible stored types; clarify the intended column meaning "
        "instead of guessing a conversion",
        code="ambiguous_column_type",
    )


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _convert_sheet(
    formula_sheet: Any,
    cached_sheet: Any,
    *,
    table: str,
    deadline: float,
) -> tuple[dict, list[list[object]], list[str]]:
    header_row: int | None = None
    headers: list[object] = []
    header_cells: list[str] = []
    rows: list[tuple[int, list[object]]] = []
    formula_cells: list[dict] = []
    date_cells: list[dict] = []
    nonempty = 0

    formula_rows = formula_sheet.iter_rows()
    cached_rows = cached_sheet.iter_rows()
    for formula_row, cached_row in zip_longest(formula_rows, cached_rows):
        _check_deadline(deadline)
        if formula_row is None or cached_row is None or len(formula_row) != len(cached_row):
            raise SpreadsheetImportError(
                f"sheet {formula_sheet.title!r} formula and cached-value views are incomplete",
                code="incomplete_conversion",
            )
        row_number = formula_row[0].row if formula_row else cached_row[0].row
        values: list[object] = []
        for formula_cell, cached_cell in zip(formula_row, cached_row, strict=True):
            if formula_cell.coordinate != cached_cell.coordinate:
                raise SpreadsheetImportError(
                    f"sheet {formula_sheet.title!r} cell views disagree at row {row_number}",
                    code="incomplete_conversion",
                )
            formula_value = formula_cell.value
            cached_value = cached_cell.value
            if formula_value is not None or cached_value is not None:
                nonempty += 1
                if nonempty > MAX_SELECTED_NONEMPTY_CELLS:
                    raise SpreadsheetImportError(
                        "selected sheets exceed 200,000 nonempty cells",
                        code="selected_cells_too_large",
                    )
            if formula_cell.data_type == "f":
                if cached_value is None:
                    raise SpreadsheetImportError(
                        f"selected formula cell {formula_sheet.title}!{formula_cell.coordinate} "
                        "has no stored cached value; correct it or explicitly exclude the "
                        "cell/sheet "
                        "through a new reviewed selection",
                        code="missing_formula_cache",
                    )
                if cached_cell.data_type == "e" or cached_value in _ERROR_VALUES:
                    raise SpreadsheetImportError(
                        f"selected formula cell {formula_sheet.title}!{formula_cell.coordinate} "
                        f"has an error cached value ({cached_value})",
                        code="error_formula_cache",
                    )
                formula_cells.append(
                    {
                        "cell": formula_cell.coordinate,
                        "formula": str(formula_value).removeprefix("="),
                        "cached_value": _json_value(cached_value),
                        "cached_type": cached_cell.data_type,
                        "cache_freshness": "unknown",
                    }
                )
            elif formula_value != cached_value:
                raise SpreadsheetImportError(
                    f"sheet {formula_sheet.title}!{formula_cell.coordinate} has inconsistent "
                    "formula and stored-value views",
                    code="incomplete_conversion",
                )
            if formula_cell.data_type == "e" or cached_cell.data_type == "e":
                raise SpreadsheetImportError(
                    f"stored error cell {formula_sheet.title}!{formula_cell.coordinate} "
                    "is not queryable data",
                    code="unsupported_stored_type",
                )
            if cached_value is not None and not isinstance(
                cached_value,
                (str, bool, int, float, datetime, date, datetime_time, timedelta),
            ):
                raise SpreadsheetImportError(
                    f"stored cell {formula_sheet.title}!{formula_cell.coordinate} has unsupported "
                    f"type {type(cached_value).__name__}",
                    code="unsupported_stored_type",
                )
            if cached_cell.data_type == "d" or isinstance(
                cached_value, (datetime, date, datetime_time, timedelta)
            ):
                date_cells.append(
                    {
                        "cell": cached_cell.coordinate,
                        "stored_type": cached_cell.data_type,
                        "number_format": cached_cell.number_format,
                        "interpreted_value": _json_value(cached_value),
                    }
                )
            values.append(cached_value)

        if header_row is None:
            if all(value is None for value in values):
                continue
            if any(cell.data_type == "f" for cell in formula_row):
                raise SpreadsheetImportError(
                    f"sheet {formula_sheet.title!r} has a formula in its header row",
                    code="invalid_header",
                )
            header_row = row_number
            headers = values
            header_cells = [cell.coordinate for cell in formula_row]
            continue

        if len(values) > len(headers) and any(
            value is not None for value in values[len(headers) :]
        ):
            raise SpreadsheetImportError(
                f"sheet {formula_sheet.title!r} row {row_number} has data outside its header",
                code="incomplete_conversion",
            )
        padded = values[: len(headers)] + [None] * max(0, len(headers) - len(values))
        if any(value is not None for value in padded):
            rows.append((row_number, padded))

    if header_row is None:
        raise SpreadsheetImportError(
            f"selected sheet {formula_sheet.title!r} has no header row",
            code="empty_selection",
        )

    used: set[str] = set()
    columns = []
    for index, header in enumerate(headers, start=1):
        values = [row_values[index - 1] for _row, row_values in rows]
        columns.append(
            {
                "name": _unique_name(header, f"column_{index}", used),
                "source_header": _json_value(header),
                "header_cell": header_cells[index - 1],
                "interpreted_type": _duckdb_type(
                    values, f"{formula_sheet.title}!{header_cells[index - 1]}"
                ),
            }
        )
    record = {
        "name": formula_sheet.title,
        "table": table,
        "header_row": header_row,
        "source_rows": [row_number for row_number, _values in rows],
        "row_count": len(rows),
        "nonempty_cell_count": nonempty,
        "columns": columns,
        "formula_cells": formula_cells,
        "date_cells": date_cells,
    }
    duckdb_rows = [[row_number, *values] for row_number, values in rows]
    return record, duckdb_rows, [column["name"] for column in columns]


def _convert_stage(
    source: Path,
    selected: list[str],
    stage: Path,
    final: Path,
    source_digest: str,
    selection_identity: str,
    deadline: float,
) -> dict:
    try:
        from openpyxl import load_workbook  # pyright: ignore[reportMissingImports]
    except ImportError as exc:
        raise SpreadsheetImportError(
            "XLSX import requires the optional ariadne-data[spreadsheets] extra",
            code="missing_dependency",
        ) from exc

    formula_book = None
    cached_book = None
    artifact = stage / "data.duckdb"
    provenance_path = stage / "provenance.json"
    try:
        formula_book = load_workbook(
            source, read_only=True, data_only=False, keep_links=False, keep_vba=False
        )
        cached_book = load_workbook(
            source, read_only=True, data_only=True, keep_links=False, keep_vba=False
        )
        _check_deadline(deadline)
        missing = sorted(set(selected) - set(formula_book.sheetnames))
        if missing:
            raise SpreadsheetImportError(
                f"selected worksheet(s) are absent: {', '.join(missing)}",
                code="missing_sheet",
            )
        table_names: set[str] = set()
        converted = []
        for name in selected:
            table = _unique_name(name, "sheet", table_names)
            record, rows, columns = _convert_sheet(
                formula_book[name], cached_book[name], table=table, deadline=deadline
            )
            converted.append((record, rows, columns))
    finally:
        if formula_book is not None:
            formula_book.close()
        if cached_book is not None:
            cached_book.close()

    connection = duckdb.connect(str(artifact))
    try:
        for record, rows, columns in converted:
            definitions = ["__ariadne_source_row BIGINT"] + [
                f"{_quote(column['name'])} {column['interpreted_type']}"
                for column in record["columns"]
            ]
            statement = f"CREATE TABLE {_quote(record['table'])} ({', '.join(definitions)})"
            # pi-lens-ignore: python-sql-injection — normalized identifiers only
            connection.execute(statement)  # nosemgrep
            if rows:
                placeholders = ", ".join("?" for _column in [0, *columns])
                insert = f"INSERT INTO {_quote(record['table'])} VALUES ({placeholders})"
                # pi-lens-ignore: python-sql-injection — normalized table, parameterized rows
                connection.executemany(insert, rows)  # nosemgrep
        connection.execute("CHECKPOINT")
    finally:
        connection.close()
    _check_deadline(deadline)
    artifact.chmod(0o444)
    artifact_digest = _sha256(artifact, deadline)
    final_artifact = final / "data.duckdb"
    final_provenance = final / "provenance.json"
    sheets = [record for record, _rows, _columns in converted]
    limitations = [
        "Stored formula caches are used without evaluation; cache freshness is unknown.",
        "Macros and external links are never executed or fetched; external links refuse import.",
        "Only explicitly selected sheets were converted; all other sheets are excluded.",
        "Business meanings, units, currencies, and joins are not inferred.",
    ]
    result = {
        "source_sha256": source_digest,
        "source_version": source_digest,
        "sheet_selection": selected,
        "selection_identity": selection_identity,
        "derived_source": {
            "identity": selection_identity,
            "type": "duckdb",
            "path": str(final_artifact),
            "tables": [sheet["table"] for sheet in sheets],
        },
        "artifact_path": str(final_artifact),
        "provenance_path": str(final_provenance),
        "artifact_sha256": artifact_digest,
        "cache_freshness": "unknown",
        "formula_evaluation": False,
        "recalculation": False,
        "sheets": sheets,
        "limitations": limitations,
    }
    with provenance_path.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    provenance_path.chmod(0o444)
    return result


def _worker(
    source: str,
    selected: list[str],
    stage: str,
    final: str,
    source_digest: str,
    selection_identity: str,
    deadline: float,
    connection: Any,
) -> None:
    try:
        result = _convert_stage(
            Path(source),
            selected,
            Path(stage),
            Path(final),
            source_digest,
            selection_identity,
            deadline,
        )
        connection.send({"ok": True, "result": result})
    except SpreadsheetImportError as exc:
        connection.send({"ok": False, "code": exc.code, "message": str(exc)})
    except Exception as exc:
        connection.send({"ok": False, "code": "conversion_failed", "message": str(exc)})
    finally:
        connection.close()


def _completed(final: Path, source_digest: str, selection_identity: str) -> dict:
    try:
        record = json.loads((final / "provenance.json").read_text(encoding="utf-8"))
        artifact = final / "data.duckdb"
        if (
            record["source_sha256"] != source_digest
            or record["selection_identity"] != selection_identity
            or record["artifact_path"] != str(artifact)
            or record["provenance_path"] != str(final / "provenance.json")
            or _sha256(artifact) != record["artifact_sha256"]
        ):
            raise ValueError("identity or artifact digest mismatch")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SpreadsheetImportError(
            f"existing derived output {final} is incomplete or does not match its identity; "
            "preserve it for operator resolution rather than overwriting it",
            code="incomplete_artifact",
        ) from exc
    return {**record, "reused": True}


def import_workbook(source: str | Path, *, sheets: Sequence[str], output: str | Path) -> dict:
    """Convert stored values without Excel execution and atomically retain a new artifact."""
    started = time.monotonic()
    deadline = started + CONVERSION_DEADLINE_SECONDS
    output_root = Path(output).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    source_path = Path(source).resolve()
    try:
        size = source_path.stat().st_size
    except OSError as exc:
        raise SpreadsheetImportError(
            "the authorized workbook bytes are unavailable", code="workbook_unavailable"
        ) from exc
    if not source_path.is_file() or size == 0:
        raise SpreadsheetImportError(
            "source must be a nonempty regular XLSX file", code="invalid_workbook"
        )
    if size > MAX_WORKBOOK_BYTES:
        raise SpreadsheetImportError(
            "XLSX input exceeds the 25 MiB compressed-input limit", code="input_too_large"
        )
    selected = _selected_sheets(sheets)
    source_digest = _sha256(source_path, deadline)
    selection_identity = hashlib.sha256(
        json.dumps(
            {"source_sha256": source_digest, "sheets": selected},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    final = output_root / selection_identity
    if final.exists():
        return _completed(final, source_digest, selection_identity)
    _preflight_archive(source_path, deadline)
    stage = Path(tempfile.mkdtemp(prefix=".import-", dir=output_root))
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker,
        args=(
            str(source_path),
            selected,
            str(stage),
            str(final),
            source_digest,
            selection_identity,
            deadline,
            sender,
        ),
        daemon=True,
    )
    result = None
    try:
        process.start()
        sender.close()
        while result is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SpreadsheetImportError(
                    "XLSX conversion exceeded the 20-second worker deadline; "
                    "no artifact was activated",
                    code="conversion_deadline",
                )
            if receiver.poll(min(0.1, remaining)):
                result = receiver.recv()
                break
            if process.exitcode is not None:
                if receiver.poll(0):
                    result = receiver.recv()
                    break
                raise SpreadsheetImportError(
                    f"XLSX conversion worker exited without a result ({process.exitcode})",
                    code="conversion_failed",
                )
        process.join(timeout=max(0.0, deadline - time.monotonic()))
        if process.is_alive():
            raise SpreadsheetImportError(
                "XLSX conversion worker did not stop before its deadline",
                code="conversion_deadline",
            )
        if not result.get("ok"):
            raise SpreadsheetImportError(result["message"], code=result["code"])
        record = result["result"]
        if (
            record["source_sha256"] != source_digest
            or record["selection_identity"] != selection_identity
        ):
            raise SpreadsheetImportError(
                "conversion worker returned the wrong source identity", code="conversion_failed"
            )
        try:
            stage.rename(final)
        except OSError:
            if final.exists():
                return _completed(final, source_digest, selection_identity)
            raise
        return {**record, "reused": False}
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        sender.close()
        if stage.exists():
            shutil.rmtree(stage)
