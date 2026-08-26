from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import openpyxl

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.lib.google_sheets_data import (
    EXPECTED_HEADERS_BY_TAB,
    build_rows,
    clear_values,
    ensure_expected_headers,
    ensure_table,
    get_values,
    make_credentials,
    normalize_date,
    parse_existing_table,
    put_values,
)


CONFIG = ROOT / "config" / "scorecard.json"
DATA_AND_ANALYTICS = Path(
    r"C:\Users\mschneider\SME\SME Media Team - Data and Analytics"
)

SOURCE_SHEETS = {
    "Monthly Media Data": (
        DATA_AND_ANALYTICS / "Monthly Scorecard.xlsx",
        "SME Media Data",
    ),
    "Monthly Media Detail": (
        DATA_AND_ANALYTICS / "Monthly Scorecard.xlsx",
        "SME Media Data (Detail)",
    ),
    "Monthly Engagement": (
        DATA_AND_ANALYTICS / "Monthly Scorecard.xlsx",
        "SME Media Engagement Metrics",
    ),
    "Weekly Media Data": (
        DATA_AND_ANALYTICS / "Weekly Scorecard.xlsx",
        "SME Media Data",
    ),
}


def source_records(workbook_path: Path, sheet_name: str) -> dict[str, dict[str, Any]]:
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    worksheet = workbook[sheet_name]
    rows = list(worksheet.iter_rows(values_only=True))
    if not rows:
        return {}

    headers = [str(value) if value is not None else "" for value in rows[0]]
    records: dict[str, dict[str, Any]] = {}
    for row in rows[1:]:
        if not row or row[0] in (None, ""):
            continue
        try:
            date_key = normalize_date(row[0]).isoformat()
        except ValueError:
            continue
        record: dict[str, Any] = {}
        for index, header in enumerate(headers[1:], start=1):
            if header:
                record[header] = row[index] if index < len(row) else ""
        records[date_key] = record
    return records


def load_google_config() -> tuple[str, Path]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    sheet_config = config["google_sheet"]
    return sheet_config["spreadsheet_id"], Path(sheet_config["service_account_file"])


def sync_tab(
    credentials: Any,
    spreadsheet_id: str,
    tab_name: str,
    workbook_path: Path,
    source_sheet_name: str,
) -> tuple[int, int]:
    current_rows = get_values(credentials, spreadsheet_id, tab_name)
    current_headers, current_records = parse_existing_table(
        current_rows,
        EXPECTED_HEADERS_BY_TAB[tab_name][0],
    )
    headers = ensure_expected_headers(tab_name, current_headers)
    workbook_records = source_records(workbook_path, source_sheet_name)
    date_keys = sorted(set(current_records) | set(workbook_records))

    records: dict[str, dict[str, Any]] = {}
    for date_key in date_keys:
        source_values = workbook_records.get(date_key, {})
        current_values = current_records.get(date_key, {})
        merged = {
            header: source_values.get(header, "")
            for header in headers[1:]
        }
        for header, value in current_values.items():
            if value not in ("", None):
                merged[header] = value
        records[date_key] = merged

    rows = build_rows(headers, records)
    clear_values(credentials, spreadsheet_id, tab_name)
    put_values(credentials, spreadsheet_id, tab_name, rows)
    ensure_table(credentials, spreadsheet_id, tab_name, headers, len(rows))
    return len(rows), len(headers)


def main() -> None:
    spreadsheet_id, service_account_file = load_google_config()
    credentials = make_credentials(service_account_file)
    for tab_name, (workbook_path, source_sheet_name) in SOURCE_SHEETS.items():
        rows, columns = sync_tab(
            credentials,
            spreadsheet_id,
            tab_name,
            workbook_path,
            source_sheet_name,
        )
        print(f"{tab_name}: {rows} rows x {columns} columns")


if __name__ == "__main__":
    main()
