from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.lib.google_sheets_data import (
    build_rows,
    clear_values,
    ensure_expected_headers,
    ensure_table,
    get_values,
    make_credentials,
    normalize_formula_owned_cells,
    parse_existing_table,
    put_values,
)
from scripts.pipelines.monthly_pipeline import WORKBOOK_FORMULA_COLUMNS


TAB_NAME = "Monthly Media Data"
SOURCE_SHEET_NAME = "SME Media Data"
DATE_COLUMN = "Month"


def main() -> None:
    config = json.loads((ROOT / "config" / "scorecard.json").read_text())
    sheet_config = config["google_sheet"]
    spreadsheet_id = sheet_config["spreadsheet_id"]
    credentials = make_credentials(sheet_config["service_account_file"])

    rows = get_values(credentials, spreadsheet_id, TAB_NAME)
    headers, records = parse_existing_table(rows, DATE_COLUMN)
    headers = ensure_expected_headers(TAB_NAME, headers)
    if not records:
        print(f"{TAB_NAME}: no records found.")
        return

    latest_date = sorted(records)[-1]
    formula_columns = {
        header
        for header in WORKBOOK_FORMULA_COLUMNS[SOURCE_SHEET_NAME]
        if header in headers
    }
    before = {
        header: records[latest_date].get(header, "")
        for header in sorted(formula_columns)
    }
    normalize_formula_owned_cells(headers, records, formula_columns, {latest_date})
    after = {
        header: records[latest_date].get(header, "")
        for header in sorted(formula_columns)
    }

    clear_values(credentials, spreadsheet_id, TAB_NAME)
    put_values(credentials, spreadsheet_id, TAB_NAME, build_rows(headers, records))
    ensure_table(credentials, spreadsheet_id, TAB_NAME, headers, len(records) + 1)

    print(f"{TAB_NAME} {latest_date}: repaired formula-owned values")
    for header in sorted(formula_columns):
        if before[header] != after[header]:
            print(f"  {header}: {before[header]!r} -> {after[header]!r}")


if __name__ == "__main__":
    main()
