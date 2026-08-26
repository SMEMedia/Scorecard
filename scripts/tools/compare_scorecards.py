from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import openpyxl

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.lib.google_sheets_data import (
    SHEETS_API,
    authorized_request,
    get_values,
    make_credentials,
    normalize_date,
    normalize_scorecard_value,
    number_value,
    parse_existing_table,
    spreadsheet_metadata,
)

DEFAULT_CONFIG = PROJECT_ROOT / "config" / "scorecard.json"
DISCREPANCY_TAB = "Discrepancies"
OUTPUT_HEADERS = [
    "Rank", "Sheet", "Date", "Column", "Excel Value", "Google Value",
    "Absolute Difference", "Percent Difference", "Discrepancy Type",
]


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; use YYYY-MM-DD."
        ) from error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare Excel Scorecard sources with the shared Google Sheet."
    )
    parser.add_argument("--scorecard-config", default=str(DEFAULT_CONFIG))
    date_group = parser.add_mutually_exclusive_group()
    date_group.add_argument("--date", type=parse_iso_date, help="Compare one exact date (YYYY-MM-DD).")
    date_group.add_argument("--start-date", type=parse_iso_date, help="First date, inclusive (YYYY-MM-DD).")
    parser.add_argument("--end-date", type=parse_iso_date, help="Last date, inclusive (YYYY-MM-DD).")
    parser.add_argument("--dry-run", action="store_true", help="Compare without updating the tab.")
    return parser.parse_args()


def comparison_window(args: argparse.Namespace) -> tuple[date | None, date | None]:
    if args.date:
        return args.date, args.date
    if args.end_date and not args.start_date:
        raise ValueError("--end-date requires --start-date.")
    if args.start_date and args.end_date and args.start_date > args.end_date:
        raise ValueError("--start-date cannot be after --end-date.")
    return args.start_date, args.end_date


def in_window(date_key: str, start: date | None, end: date | None) -> bool:
    row_date = date.fromisoformat(date_key)
    return (start is None or row_date >= start) and (end is None or row_date <= end)


def excel_records(workbook_path: Path, sheet_name: str) -> tuple[list[str], dict[str, dict[str, Any]]]:
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        worksheet = workbook[sheet_name]
        rows = worksheet.iter_rows(values_only=True)
        first_row = next(rows, None)
        if not first_row:
            return [], {}
        headers = [str(value).strip() if value is not None else "" for value in first_row]
        records: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not row or row[0] in (None, ""):
                continue
            try:
                date_key = normalize_date(row[0]).isoformat()
            except (TypeError, ValueError):
                continue
            records[date_key] = {
                header: row[index] if index < len(row) else ""
                for index, header in enumerate(headers[1:], start=1)
                if header
            }
        return headers, records
    finally:
        workbook.close()


def normalized_value(header: str, value: Any) -> Any:
    if value in (None, ""):
        return ""
    if isinstance(value, (datetime, date)):
        return normalize_date(value).isoformat()
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    if header == "Avg. View Duration*" and isinstance(value, str):
        return value.lstrip("'")
    return normalize_scorecard_value(header, value)


def values_match(left: Any, right: Any) -> bool:
    if left in (None, "") and right in (None, ""):
        return True
    left_number = number_value(left)
    right_number = number_value(right)
    if left_number is not None and right_number is not None:
        return math.isclose(left_number, right_number, rel_tol=1e-9, abs_tol=1e-9)
    return str(left).strip() == str(right).strip()


def make_discrepancy(tab: str, date_key: str, header: str, excel_value: Any, google_value: Any) -> dict[str, Any]:
    excel_number = number_value(excel_value)
    google_number = number_value(google_value)
    absolute: float | str = ""
    percent: float | str = ""
    if excel_number is not None and google_number is not None:
        absolute = abs(google_number - excel_number)
        percent = absolute / abs(excel_number) if excel_number else (1.0 if absolute else 0.0)
    if excel_value == "":
        kind = "Missing in Excel"
    elif google_value == "":
        kind = "Missing in Google"
    elif excel_number is not None and google_number is not None:
        kind = "Numeric difference"
    else:
        kind = "Text difference"
    severity = percent if isinstance(percent, float) else absolute if isinstance(absolute, float) else math.inf
    if kind.startswith("Missing"):
        severity = math.inf
    return {
        "sheet": tab, "date": date_key, "column": header,
        "excel": excel_value, "google": google_value,
        "absolute": absolute, "percent": percent, "type": kind, "severity": severity,
    }


def compare_source(credentials: Any, spreadsheet_id: str, source: dict[str, str], start: date | None, end: date | None) -> list[dict[str, Any]]:
    excel_headers, excel_data = excel_records(Path(source["workbook"]), source["excel_sheet"])
    google_rows = get_values(credentials, spreadsheet_id, source["google_tab"])
    google_headers, google_data = parse_existing_table(google_rows, excel_headers[0] if excel_headers else "Date")
    common_headers = [header for header in excel_headers[1:] if header and header in google_headers]
    discrepancies = []
    for date_key in sorted(set(excel_data) | set(google_data)):
        if not in_window(date_key, start, end):
            continue
        excel_row = excel_data.get(date_key, {})
        google_row = google_data.get(date_key, {})
        for header in common_headers:
            excel_value = normalized_value(header, excel_row.get(header, ""))
            google_value = normalized_value(header, google_row.get(header, ""))
            if not values_match(excel_value, google_value):
                discrepancies.append(make_discrepancy(source["google_tab"], date_key, header, excel_value, google_value))
    return discrepancies


def output_rows(discrepancies: list[dict[str, Any]]) -> list[list[Any]]:
    ordered = sorted(
        discrepancies,
        key=lambda item: (
            item["severity"],
            item["absolute"] if isinstance(item["absolute"], float) else -1,
            item["date"], item["sheet"], item["column"],
        ),
        reverse=True,
    )
    rows = [OUTPUT_HEADERS]
    for rank, item in enumerate(ordered, start=1):
        rows.append([
            rank, item["sheet"], item["date"], item["column"], item["excel"], item["google"],
            item["absolute"], item["percent"], item["type"],
        ])
    return rows


def update_discrepancy_tab(credentials: Any, spreadsheet_id: str, rows: list[list[Any]]) -> None:
    metadata = spreadsheet_metadata(credentials, spreadsheet_id)
    sheets = {sheet["properties"]["title"]: sheet for sheet in metadata.get("sheets", [])}
    if DISCREPANCY_TAB not in sheets:
        authorized_request(
            credentials, f"{SHEETS_API}/{spreadsheet_id}:batchUpdate", method="POST",
            payload={"requests": [{"addSheet": {"properties": {"title": DISCREPANCY_TAB}}}]},
        )
        metadata = spreadsheet_metadata(credentials, spreadsheet_id)
        sheets = {sheet["properties"]["title"]: sheet for sheet in metadata.get("sheets", [])}
    sheet_id = sheets[DISCREPANCY_TAB]["properties"]["sheetId"]
    authorized_request(
        credentials, f"{SHEETS_API}/{spreadsheet_id}/values/{DISCREPANCY_TAB}!A:I:clear",
        method="POST", payload={},
    )
    authorized_request(
        credentials, f"{SHEETS_API}/{spreadsheet_id}/values/{DISCREPANCY_TAB}!A1?valueInputOption=USER_ENTERED",
        method="PUT", payload={"majorDimension": "ROWS", "values": rows},
    )
    end_row = max(len(rows), 2)
    requests = [
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 9}, "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.85}, "textFormat": {"bold": True}}}, "fields": "userEnteredFormat(backgroundColor,textFormat)"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": end_row, "startColumnIndex": 2, "endColumnIndex": 3}, "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "M/d/yyyy"}}}, "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": end_row, "startColumnIndex": 6, "endColumnIndex": 7}, "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0.000"}}}, "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": end_row, "startColumnIndex": 7, "endColumnIndex": 8}, "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0.0%"}}}, "fields": "userEnteredFormat.numberFormat"}},
        {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}},
        {"setBasicFilter": {"filter": {"range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": end_row, "startColumnIndex": 0, "endColumnIndex": 9}}}},
        {"autoResizeDimensions": {"dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 9}}},
    ]
    authorized_request(
        credentials, f"{SHEETS_API}/{spreadsheet_id}:batchUpdate", method="POST",
        payload={"requests": requests},
    )


def main() -> None:
    args = parse_args()
    start, end = comparison_window(args)
    config = json.loads(Path(args.scorecard_config).read_text(encoding="utf-8"))
    google = config["google_sheet"]
    credentials = make_credentials(google["service_account_file"])
    discrepancies = []
    for source in config["discrepancy_sources"]:
        discrepancies.extend(compare_source(credentials, google["spreadsheet_id"], source, start, end))
    rows = output_rows(discrepancies)
    if not args.dry_run:
        update_discrepancy_tab(credentials, google["spreadsheet_id"], rows)
    window = args.date.isoformat() if args.date else f"{start.isoformat() if start else 'first row'} through {end.isoformat() if end else 'last row'}"
    print(f"{'Found' if args.dry_run else 'Wrote'} {len(discrepancies)} discrepancies for {window}.")


if __name__ == "__main__":
    main()
